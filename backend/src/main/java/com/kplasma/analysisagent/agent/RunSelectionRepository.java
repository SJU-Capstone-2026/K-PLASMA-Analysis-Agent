package com.kplasma.analysisagent.agent;

import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Frozen identities and display fields stay in PostgreSQL, never in Agent state. */
@Repository
public class RunSelectionRepository {
    private final JdbcTemplate jdbc;
    private final AgentRequestRepository json;
    public RunSelectionRepository(JdbcTemplate jdbc,AgentRequestRepository json){this.jdbc=jdbc;this.json=json;}
    public record Session(UUID id,long revision,String baseline,long total) {}
    public Session find(UUID request,String pending){
        var rows=jdbc.query("select id,revision,baseline_key,total_count from agent_run_selection where request_id=? and pending_input_id=?",(rs,n)->new Session(rs.getObject(1,UUID.class),rs.getLong(2),rs.getString(3),rs.getLong(4)),request,pending);
        return rows.isEmpty()?null:rows.getFirst();
    }
    public Session create(UUID request,String pending,Map<String,Object> context){
        Session existing=find(request,pending);if(existing!=null)return existing;
        UUID id=UUID.randomUUID();jdbc.update("insert into agent_run_selection(id,request_id,pending_input_id) values (?,?,?)",id,request,pending);
        int count;
        if(context.get("comparisonOptions") instanceof Map<?,?> legacy&&Objects.equals(legacy.get("pendingInputId"),pending)&&legacy.get("options") instanceof List<?> options){
            count=jdbc.update("""
                insert into agent_run_selection_option(snapshot_id,alias,ordinal,run_id,run_version_id,conditions,selectable,unavailable_reason,natural_sort_key,search_text)
                select ?,e->>'key',ordinal,e->'ref'->>'runId',(e->'ref'->>'runVersionId')::uuid,e->'conditions',(e->>'selectable')::boolean,e->>'unavailableReason',lower(e->'ref'->>'runId'),
                run_selection_search_v1(e->>'key',e->'ref'->>'runId',(e->'ref'->>'runVersionId')::uuid,e->'conditions')
                from jsonb_array_elements(?::jsonb) with ordinality t(e,ordinal)
                """,id,json.json(options));
        }else{
            Object entries=context.get("comparisonReference") instanceof Map<?,?> reference?reference.get("entries"):null;
            count=jdbc.update("""
                with attached as materialized (
                  select e->>'key' alias,e->'ref'->>'runId' run_id,(e->'ref'->>'runVersionId')::uuid version_id,ordinal
                  from jsonb_array_elements(?::jsonb) with ordinality t(e,ordinal)
                ), candidates as materialized (
                  select v.run_id,v.id,v.summary,0 priority,0::bigint attachment_order from run r join run_version v on v.id=r.current_version_id
                  union all
                  select v.run_id,v.id,v.summary,1,a.ordinal from attached a join run_version v on v.id=a.version_id and v.run_id=a.run_id
                  where not exists(select 1 from run r where r.current_version_id=v.id)
                ), numbered as materialized (
                  select c.*,a.alias,row_number() over(order by priority,c.run_id,attachment_order,c.id) ordinal
                  from candidates c left join attached a on a.version_id=c.id and a.run_id=c.run_id
                ), free_options as (
                  select id,row_number() over(order by ordinal) sequence from numbered where alias is null
                ), free_aliases as (
                  select 'R'||n alias,row_number() over(order by n) sequence
                  from generate_series(1,(select count(*) from numbered)+(select count(*) from attached)) n
                  where not exists(select 1 from attached a where a.alias='R'||n)
                ), ready as (
                  select n.*,coalesce(n.alias,a.alias) final_alias,run_selection_conditions_v1(n.summary) conditions
                  from numbered n left join free_options f on f.id=n.id left join free_aliases a on a.sequence=f.sequence
                )
                insert into agent_run_selection_option(snapshot_id,alias,ordinal,run_id,run_version_id,conditions,selectable,unavailable_reason,natural_sort_key,search_text)
                select ?,final_alias,ordinal,run_id,id,conditions,coalesce(summary->>'catalogStatus'='READY',false),
                  case when summary->>'catalogStatus'='READY' then null else 'DATA_NOT_COMPARABLE' end,lower(run_id),
                  run_selection_search_v1(final_alias,run_id,id,conditions) from ready
                """,json.json(entries==null?List.of():entries),id);
        }
        jdbc.update("update agent_run_selection set total_count=? where id=?",count,id);
        return new Session(id,0,null,count);
    }
    static String pattern(String query){return "%"+query.toLowerCase(Locale.ROOT).replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%";}
    private static final String COLUMNS="""
        select o.alias,o.ordinal,o.run_id,o.run_version_id,o.conditions::text,o.selectable,
               o.unavailable_reason,o.selected,o.natural_sort_key,v.id is not null version_exists
        from agent_run_selection_option o left join run_version v on v.id=o.run_version_id
        """;
    private Map<String,Object> option(java.sql.ResultSet rs,int index)throws java.sql.SQLException{
        Map<String,Object> item=new LinkedHashMap<>();item.put("key",rs.getString("alias"));
        item.put("ref",Map.of("runId",rs.getString("run_id"),"runVersionId",rs.getString("run_version_id")));
        item.put("conditions",json.read(rs.getString("conditions")));item.put("selected",rs.getBoolean("selected"));
        item.put("selectable",rs.getBoolean("selectable")&&rs.getBoolean("version_exists"));
        item.put("unavailableReason",rs.getBoolean("version_exists")?rs.getString("unavailable_reason"):"RUN_VERSION_DELETED");
        item.put("_sort",rs.getString("natural_sort_key"));item.put("_ordinal",rs.getLong("ordinal"));return item;
    }
    public List<Map<String,Object>> page(UUID snapshot,String query,boolean descending,List<?> after,int limit,boolean selected){
        String sql=COLUMNS+" where o.snapshot_id=?";List<Object> args=new ArrayList<>();args.add(snapshot);
        if(selected)sql+=" and o.selected";
        if(!query.isEmpty()){sql+=" and o.search_text like ? escape E'\\\\'";args.add(pattern(query));}
        String direction=descending?" desc":" asc";
        if(after!=null){
            if(selected){sql+=" and o.ordinal>?";args.add(((Number)after.getFirst()).longValue());}
            else{sql+=" and (o.natural_sort_key,o.run_id,o.run_version_id)"+(descending?"<":">")+"(? collate run_selection_natural,?,?::uuid)";args.addAll(after);}
        }
        sql+=selected?" order by o.ordinal":" order by o.natural_sort_key"+direction+",o.run_id"+direction+",o.run_version_id"+direction;
        sql+=" limit ?";args.add(limit);return jdbc.query(sql,this::option,args.toArray());
    }
    public List<Map<String,Object>> chosen(UUID snapshot,List<String> keys){
        String where=keys==null?"o.selected":"o.alias=any(?::text[])";
        Object[] args=keys==null?new Object[]{snapshot}:new Object[]{snapshot,keys.toArray(String[]::new)};
        return jdbc.query(COLUMNS+" where o.snapshot_id=? and "+where+" order by o.ordinal",this::option,args);
    }
    public long count(UUID snapshot,String query){return jdbc.queryForObject("select count(*) from agent_run_selection_option where snapshot_id=? and search_text like ? escape E'\\\\'",Long.class,snapshot,pattern(query));}
    public Map<String,Object> selectedCounts(UUID snapshot){
        return jdbc.queryForObject("select count(*) total,count(*) filter(where not o.selectable or v.id is null) unavailable from agent_run_selection_option o left join run_version v on v.id=o.run_version_id where snapshot_id=? and selected",(rs,n)->Map.of("selectedCount",rs.getLong(1),"unavailableCount",rs.getLong(2)),snapshot);
    }
    public void delete(UUID request){jdbc.update("delete from agent_run_selection where request_id=?",request);}
}
