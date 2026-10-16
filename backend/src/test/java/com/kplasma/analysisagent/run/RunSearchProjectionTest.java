package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.workspace.WorkspaceTestSupport;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;

class RunSearchProjectionTest extends WorkspaceTestSupport {
    @Autowired RunRepository repository;
    @Autowired PlatformTransactionManager transactions;
    private Double scalar(String metric,String value,String unit){
        String path=Set.of("meanIonEnergy","ionFlux","iedWidth").contains(metric)?"metrics":"root";
        String summary="{\"units\":{\""+metric+"\":\""+unit+"\"},"+(path.equals("metrics")?"\"metrics\":{":"")+"\""+metric+"\":"+value+(path.equals("metrics")?"}":"")+"}";
        return jdbc.queryForObject("select run_search_scalar_v1(?::jsonb,?)",Double.class,summary,metric);
    }
    @Test void canonicalValuesKeepZeroUnderflowAndUnitAliases(){
        assertThat(scalar("pressure","0.003","Torr")).isEqualTo(3);
        assertThat(scalar("ionFlux","3e19","m^-2 s^-1")).isEqualTo(30);
        assertThat(scalar("ionFlux","1e-308","m^-2 s^-1")).isZero();
        assertThat(scalar("meanIonEnergy","1e-330","eV")).isZero();
        for(String unit:List.of("W","와트","왓트","왛트","오ㅏ트","watts"))assertThat(scalar("sourcePower","300",unit)).isEqualTo(300);
        for(String unit:List.of("eV","e볼트","전자볼트"))assertThat(scalar("meanIonEnergy","155",unit)).isEqualTo(155);
        for(String space:List.of("\u00a0","\u0085","\u2007","\u202f","\u3000")) {
            assertThat(scalar("pressure","8",space+"mTorr"+space)).isEqualTo(8);
            assertThat(scalar("sourcePower","300",space+"W"+space)).isEqualTo(300);
            assertThat(scalar("meanIonEnergy","155","e"+space+"V")).isEqualTo(155);
        }
        assertThat(scalar("pressure","1e308","Torr")).isNull();
        assertThat(scalar("sourcePower","300","kW")).isNull();
        assertThat(scalar("meanIonEnergy","null","eV")).isNull();
        assertThat(scalar("meanIonEnergy","0","eV")).isZero();
    }
    @Test void currentVersionAndProjectionUpdateTogetherAndRollbackTogether(){
        UUID old=UUID.fromString(refs.getFirst().get("runVersionId").stringValue());
        var source=jdbc.queryForObject("select source_id from run_version where id=?",UUID.class,old);
        ObjectNode full=(ObjectNode)mapper.readTree(jdbc.queryForObject("select full_run::text from run_version where id=?",String.class,old));
        UUID updated=UUID.randomUUID();full.put("runVersionId",updated.toString());((ObjectNode)full.get("metrics")).put("meanIonEnergy",155);
        var body=mapper.treeToValue(full,RunDto.Full.class);var summary=mapper.treeToValue(full,RunDto.Summary.class);
        var transaction=new TransactionTemplate(transactions);
        transaction.executeWithoutResult(status->repository.save(source,summary,body));
        assertThat(jdbc.queryForObject("select current_version_id from run where run_id='SYNTHETIC-0'",UUID.class)).isEqualTo(updated);
        assertThat(jdbc.queryForObject("select mean_ion_energy_ev from run where run_id='SYNTHETIC-0'",Double.class)).isEqualTo(155);
        UUID failed=UUID.randomUUID();full.put("runVersionId",failed.toString());((ObjectNode)full.get("metrics")).put("meanIonEnergy",999);
        var failingBody=mapper.treeToValue(full,RunDto.Full.class);var failingSummary=mapper.treeToValue(full,RunDto.Summary.class);
        assertThatThrownBy(()->transaction.executeWithoutResult(status->{repository.save(source,failingSummary,failingBody);throw new IllegalStateException("synthetic rollback");})).isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("select count(*) from run_version where id=?",Integer.class,failed)).isZero();
        assertThat(jdbc.queryForObject("select mean_ion_energy_ev from run where run_id='SYNTHETIC-0'",Double.class)).isEqualTo(155);
        assertThat(jdbc.queryForObject("select count(*) from run",Integer.class)).isEqualTo(4);
    }
}
