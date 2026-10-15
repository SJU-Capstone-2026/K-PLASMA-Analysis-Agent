package com.kplasma.analysisagent.ingestion;

import java.lang.reflect.*;
import java.sql.*;
import javax.sql.DataSource;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.datasource.DelegatingDataSource;

/** No extra queries; wraps real JDBC calls only while an import trace is active. */
@Configuration(proxyBeanMethods=false)
@ConditionalOnProperty(name="kplasma.import-timing.enabled",havingValue="true")
public class ImportSqlTimingConfiguration {
    @Bean static BeanPostProcessor importSqlTiming() {
        return new BeanPostProcessor() {
            @Override public Object postProcessAfterInitialization(Object bean,String name) {
                return bean instanceof DataSource source?new DelegatingDataSource(source) {
                    @Override public Connection getConnection()throws SQLException {try(var ignored=ImportTimingRecorder.span("db.acquire")){return connection(super.getConnection());}}
                    @Override public Connection getConnection(String user,String password)throws SQLException {try(var ignored=ImportTimingRecorder.span("db.acquire")){return connection(super.getConnection(user,password));}}
                }:bean;
            }
        };
    }
    private static Object invoke(Object target,Method method,Object[] args)throws Throwable {
        try{return method.invoke(target,args);}catch(InvocationTargetException e){throw e.getCause();}
    }
    private static Connection connection(Connection target) {
        var held=ImportTimingRecorder.span("db.connection_held");
        return (Connection)Proxy.newProxyInstance(Connection.class.getClassLoader(),new Class<?>[]{Connection.class},(proxy,method,args)->{
            String name=method.getName();
            if(name.equals("close"))try{return invoke(target,method,args);}finally{held.close();}
            if(name.equals("commit")||name.equals("rollback"))try(var ignored=ImportTimingRecorder.span("db."+name)){return invoke(target,method,args);}
            Object value=invoke(target,method,args);
            if(value instanceof Statement statement) {
                Class<?> api=statement instanceof CallableStatement?CallableStatement.class:statement instanceof PreparedStatement?PreparedStatement.class:Statement.class;
                return Proxy.newProxyInstance(api.getClassLoader(),new Class<?>[]{api},(p,m,a)->{
                    if(m.getName().startsWith("execute"))try(var ignored=ImportTimingRecorder.span("db.execute")){return invoke(statement,m,a);}
                    return invoke(statement,m,a);
                });
            }
            return value;
        });
    }
}
