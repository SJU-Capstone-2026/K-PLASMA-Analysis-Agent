package com.kplasma.analysisagent.agent;

import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Read catalogue pages in place; persist only explicitly attached or selected exact versions. */
@Repository
public class RunSelectionRepository {
    private final JdbcTemplate jdbc;
    private final AgentRequestRepository json;
    public RunSelectionRepository(JdbcTemplate jdbc,AgentRequestRepository json){this.jdbc=jdbc;this.json=json;}
    public record Session(UUID id,long revision,String baseline,long aliasBase) {}
    public Session find(UUID request,String pending){
        var rows=jdbc.query("select id,revision,baseline_key,alias_base from agent_run_selection where request_id=? and pending_input_id=?",(rs,n)->new Session(rs.getObject(1,UUID.class),rs.getLong(2),rs.getString(3),rs.getLong(4)),request,pending);
        return rows.isEmpty()?null:rows.getFirst();
    }
    private long aliasNumber(String key){try{return key.matches("R[0-9]{1,18}")?Long.parseLong(key.substring(1)):0;}catch(Exception e){return 0;}}
    public Session create(UUID request,String pending,Map<String,Object> context){
        var existing=find(request,pending);if(existing!=null)return existing;
        List<?> entries=context.get("comparisonReference") instanceof Map<?,?> ref&&ref.get("entries") instanceof List<?> list?list:List.of();
        long base=0;for(var entry:entries)base=Math.max(base,aliasNumber(String.valueOf(((Map<?,?>)entry).get("key"))));
        // Reserve old aliases without copying an old unselected JSON inventory into new rows.
        if(context.get("comparisonOptions") instanceof Map<?,?> old&&old.get("options") instanceof List<?> list)
            for(var entry:list)base=Math.max(base,aliasNumber(String.valueOf(((Map<?,?>)entry).get("key"))));
        UUID id=UUID.randomUUID();jdbc.update("insert into agent_run_selection(id,request_id,pending_input_id,alias_base) values (?,?,?,?)",id,request,pending,base);
        if(!entries.isEmpty())jdbc.update("""
            insert into agent_run_selection_option(snapshot_id,alias,ordinal,run_id,run_version_id,conditions,selectable,unavailable_reason,natural_sort_key,search_text,attached)
            select ?,e->>'key',n,e->'ref'->>'runId',(e->'ref'->>'runVersionId')::uuid,c,
              coalesce(v.summary->>'catalogStatus'='READY',false),case when v.id is null then 'RUN_VERSION_DELETED' when v.summary->>'catalogStatus'='READY' then null else 'DATA_NOT_COMPARABLE' end,
              lower(e->'ref'->>'runId'),run_selection_search_v1(e->>'key',e->'ref'->>'runId',(e->'ref'->>'runVersionId')::uuid,c),true
            from jsonb_array_elements(?::jsonb) with ordinality t(e,n)
            left join run_version v on v.id=(e->'ref'->>'runVersionId')::uuid and v.run_id=e->'ref'->>'runId'
            cross join lateral (select run_selection_conditions_v1(v.summary) c) conditions
            """,id,json.json(entries));
        return new Session(id,0,null,base);
    }
    static String pattern(String query){return "%"+query.toLowerCase(Locale.ROOT).replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%";}
    private static final String STORED="""
        select o.alias,o.ordinal,o.run_id,o.run_version_id,o.conditions::text,o.selectable,
               o.unavailable_reason,o.selected,o.natural_sort_key,v.id is not null version_exists
        from agent_run_selection_option o left join run_version v on v.id=o.run_version_id
        """;
    private static final String LIVE="""
        select coalesce(o.alias,'R'||(s.alias_base+v.registration_sequence)) alias,
          coalesce(o.ordinal,s.alias_base+v.registration_sequence) ordinal,l.run_id,l.run_version_id,
          coalesce(o.conditions,run_selection_conditions_v1(v.summary))::text conditions,
          coalesce(o.selectable,v.summary->>'catalogStatus'='READY',false) selectable,
          coalesce(o.unavailable_reason,case when v.summary->>'catalogStatus'='READY' then null else 'DATA_NOT_COMPARABLE' end) unavailable_reason,
          coalesce(o.selected,false) selected,l.natural_sort_key,v.id is not null version_exists
        from limited l cross join agent_run_selection s
        left join run_version v on v.id=l.run_version_id
        left join agent_run_selection_option o on o.snapshot_id=s.id and o.run_version_id=l.run_version_id
        where s.id=?
        """;
    private record Query(String sql,List<Object> args) {}
    private record Catalogue(Query current,Query attached) {
        Query union(){var args=new ArrayList<>(current.args());args.addAll(attached.args());return new Query(current.sql()+" union all "+attached.sql(),args);}
    }
    private Catalogue catalogue(UUID session,String query){
        List<Object> args=new ArrayList<>();String filter="";
        if(!query.isEmpty()){
            filter=" and (r.run_id,r.current_version_id) in (select run_id,id from run_version where picker_search_text like ? escape E'\\\\'";args.add(pattern(query));
            if(query.trim().matches("(?i)r[0-9]+")){
                filter+=" or lower('R'||((select alias_base from agent_run_selection where id=?)+registration_sequence)) like ? escape E'\\\\'";
                args.add(session);args.add(pattern(query));
                filter+=") or (r.run_id,r.current_version_id) in (select run_id,run_version_id from agent_run_selection_option where snapshot_id=? and search_text like ? escape E'\\\\')";
                args.add(session);args.add(pattern(query));
                filter=" and ("+filter.substring(5)+")";
            }else filter+=")";
        }
        String current="select r.run_id,r.current_version_id run_version_id,r.picker_sort_key natural_sort_key from run r where r.current_version_id is not null"+filter;
        String attached="select o.run_id,o.run_version_id,o.natural_sort_key from agent_run_selection_option o where o.snapshot_id=? and o.attached and not exists(select 1 from run r where r.current_version_id=o.run_version_id)";
        var attachedArgs=new ArrayList<Object>(List.of(session));if(!query.isEmpty()){attached+=" and o.search_text like ? escape E'\\\\'";attachedArgs.add(pattern(query));}
        return new Catalogue(new Query(current,args),new Query(attached,attachedArgs));
    }
    private Map<String,Object> option(java.sql.ResultSet rs,int index)throws java.sql.SQLException{
        Map<String,Object> item=new LinkedHashMap<>();item.put("key",rs.getString("alias"));
        item.put("ref",Map.of("runId",rs.getString("run_id"),"runVersionId",rs.getString("run_version_id")));
        item.put("conditions",json.read(rs.getString("conditions")));item.put("selected",rs.getBoolean("selected"));
        item.put("selectable",rs.getBoolean("selectable")&&rs.getBoolean("version_exists"));
        item.put("unavailableReason",rs.getBoolean("version_exists")?rs.getString("unavailable_reason"):"RUN_VERSION_DELETED");
        item.put("_sort",rs.getString("natural_sort_key"));item.put("_ordinal",rs.getLong("ordinal"));return item;
    }
    public List<Map<String,Object>> page(UUID session,String query,boolean descending,List<?> after,int limit,boolean selected){
        if(selected){List<Object> args=new ArrayList<>(List.of(session));String where=" where o.snapshot_id=? and o.selected";
            if(after!=null){where+=" and o.ordinal>?";args.add(((Number)after.getFirst()).longValue());}
            args.add(limit);return jdbc.query(STORED+where+" order by o.ordinal limit ?",this::option,args.toArray());}
        var catalogue=catalogue(session,query);
        var source=catalogue.current();
        // Resolve selective matches first. Otherwise ORDER BY/LIMIT can make PostgreSQL
        // probe every version in catalogue order even when GIN finds zero or one match.
        // Two-character searches keep the ordered path; trigram cannot narrow them well.
        if(query.codePointCount(0,query.length())>=3)source=new Query("with matches as materialized ("+source.sql()+") select * from matches",source.args());
        var current=bounded(source,after,descending,limit);
        var attached=bounded(catalogue.attached(),after,descending,limit);
        var args=new ArrayList<>(current.args());args.addAll(attached.args());args.add(limit);args.add(session);
        String order=order(descending);
        // Bound each branch before UNION: PostgreSQL otherwise may sort the whole catalogue
        // instead of using the original table's ordered index. Metadata still loads only 31 rows.
        return jdbc.query("with limited as materialized (select * from (("+current.sql()+") union all ("+attached.sql()+")) candidates"+order+" limit ?) "+LIVE+order,this::option,args.toArray());
    }
    private static String order(boolean descending){String direction=descending?" desc":" asc";return " order by natural_sort_key"+direction+",run_id"+direction+",run_version_id"+direction;}
    private Query bounded(Query source,List<?> after,boolean descending,int limit){
        var args=new ArrayList<>(source.args());String where="";
        if(after!=null){where=" where (natural_sort_key,run_id,run_version_id)"+(descending?"<":">")+"(? collate run_selection_natural,?,?::uuid)";args.addAll(after);}
        args.add(limit);return new Query("select * from ("+source.sql()+") candidates"+where+order(descending)+" limit ?",args);
    }

    public List<Map<String,Object>> chosen(UUID session,List<String> keys){
        if(keys==null)return jdbc.query(STORED+" where o.snapshot_id=? and o.selected order by o.ordinal",this::option,session);
        var found=new ArrayList<>(jdbc.query(STORED+" where o.snapshot_id=? and o.alias=any(?::text[]) order by o.ordinal",this::option,session,keys.toArray(String[]::new)));
        var known=new HashSet<String>();found.forEach(o->known.add((String)o.get("key")));
        long base=jdbc.queryForObject("select alias_base from agent_run_selection where id=?",Long.class,session);
        var numbers=keys.stream().filter(k->!known.contains(k)).map(this::aliasNumber).filter(n->n>base).map(n->n-base).toArray(Long[]::new);
        if(numbers.length>0){var extra=jdbc.query("with limited as materialized (select run_id,id run_version_id,lower(run_id) collate run_selection_natural natural_sort_key from run_version where registration_sequence=any(?::bigint[])) "+LIVE,this::option,numbers,session);
            for(var row:extra)if(keys.contains(row.get("key"))&&known.add((String)row.get("key")))found.add(row);}
        return found;
    }
    public void pin(UUID session,List<Map<String,Object>> rows){
        for(var row:rows){var ref=(Map<?,?>)row.get("ref");jdbc.update("""
            insert into agent_run_selection_option(snapshot_id,alias,ordinal,run_id,run_version_id,conditions,selectable,unavailable_reason,selected,natural_sort_key,search_text)
            values (?,?,?,?,?::uuid,?::jsonb,?,?,true,?,run_selection_search_v1(?,?,?::uuid,?::jsonb))
            on conflict(snapshot_id,run_version_id) do update set selected=true
            """,session,row.get("key"),row.get("_ordinal"),ref.get("runId"),ref.get("runVersionId"),json.json(row.get("conditions")),row.get("selectable"),row.get("unavailableReason"),row.get("_sort"),row.get("key"),ref.get("runId"),ref.get("runVersionId"),json.json(row.get("conditions")));}
    }
    public void selectAll(UUID session,String query){
        var catalogue=catalogue(session,query).union();var args=new ArrayList<>(catalogue.args());args.add(session);args.add(session);
        jdbc.update("with limited as materialized ("+catalogue.sql()+"), ready as ("+LIVE+") "+"""
            insert into agent_run_selection_option(snapshot_id,alias,ordinal,run_id,run_version_id,conditions,selectable,unavailable_reason,selected,natural_sort_key,search_text)
            select ?,alias,ordinal,run_id,run_version_id,conditions::jsonb,selectable,unavailable_reason,true,natural_sort_key,
              run_selection_search_v1(alias,run_id,run_version_id,conditions::jsonb) from ready where selectable and version_exists
            on conflict(snapshot_id,run_version_id) do update set selected=true
            """,args.toArray());
    }
    public void remove(UUID session,List<String> keys){jdbc.update("delete from agent_run_selection_option where snapshot_id=? and not attached and alias=any(?::text[])",session,keys.toArray(String[]::new));jdbc.update("update agent_run_selection_option set selected=false where snapshot_id=? and alias=any(?::text[])",session,keys.toArray(String[]::new));}
    public void clear(UUID session){jdbc.update("delete from agent_run_selection_option where snapshot_id=? and not attached",session);jdbc.update("update agent_run_selection_option set selected=false where snapshot_id=?",session);}
    public long count(UUID session,String query){var q=catalogue(session,query).union();return jdbc.queryForObject("select count(*) from ("+q.sql()+") candidates",Long.class,q.args().toArray());}
    public Map<String,Object> selectedCounts(UUID session){return jdbc.queryForObject("select count(*) total,count(*) filter(where not o.selectable or v.id is null) unavailable from agent_run_selection_option o left join run_version v on v.id=o.run_version_id where snapshot_id=? and selected",(rs,n)->Map.of("selectedCount",rs.getLong(1),"unavailableCount",rs.getLong(2)),session);}
    public void delete(UUID request){jdbc.update("delete from agent_run_selection where request_id=?",request);}
}
