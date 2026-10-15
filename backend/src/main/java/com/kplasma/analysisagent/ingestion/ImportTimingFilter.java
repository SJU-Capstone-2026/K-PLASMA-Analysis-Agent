package com.kplasma.analysisagent.ingestion;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component @Order(Ordered.HIGHEST_PRECEDENCE)
@ConditionalOnProperty(name="kplasma.import-timing.enabled",havingValue="true")
public class ImportTimingFilter extends OncePerRequestFilter {
    private final ImportTimingRecorder recorder;
    public ImportTimingFilter(){this(ImportTimingRecorder.system());}
    ImportTimingFilter(ImportTimingRecorder recorder){this.recorder=recorder;}
    private String kind(HttpServletRequest request){
        String path=request.getRequestURI();
        if("POST".equals(request.getMethod())&&path.equals("/api/import-batches"))return "request";
        if("GET".equals(request.getMethod())){
            if(path.startsWith("/api/run-versions/"))return "lookup";
            if(path.startsWith("/api/import-batches/"))return "poll";
        }
        return null;
    }
    @Override protected boolean shouldNotFilter(HttpServletRequest request){return kind(request)==null;}
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)throws ServletException,IOException {
        String id=request.getHeader("X-Benchmark-Request-Id");
        if(id==null||!id.matches("[A-Za-z0-9_-]{1,96}"))id=UUID.randomUUID().toString();
        try(var trace=recorder.begin(kind(request),id)){
            try{chain.doFilter(request,response);trace.field("status",response.getStatus());}
            catch(ServletException|IOException|RuntimeException e){trace.field("status",500);trace.field("outcome","error");throw e;}
        }
    }
}
