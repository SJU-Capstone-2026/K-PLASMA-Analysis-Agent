package com.kplasma.analysisagent.health;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.SQLException;
import javax.sql.DataSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {
    private final DataSource dataSource;
    private final Path storageRoot;

    public HealthController(DataSource dataSource, @Value("${kplasma.storage-root}") Path storageRoot) {
        this.dataSource = dataSource;
        this.storageRoot = storageRoot;
    }

    @GetMapping("/api/health")
    public HealthView health() {
        String database = databaseReady() ? "UP" : "DOWN";
        String storage = storageReady() ? "UP" : "DOWN";
        boolean ready = database.equals("UP") && storage.equals("UP");
        HealthView view = new HealthView(ready ? "UP" : "DOWN", database, storage);
        if (!ready) {
            throw new NotReady(view);
        }
        return view;
    }

    @ExceptionHandler(NotReady.class)
    ResponseEntity<HealthView> notReady(NotReady exception) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(exception.view);
    }

    private boolean databaseReady() {
        try (var connection = dataSource.getConnection(); var statement = connection.createStatement()) {
            statement.setQueryTimeout(2);
            try (var result = statement.executeQuery("SELECT 1")) {
                return result.next() && result.getInt(1) == 1;
            }
        } catch (SQLException exception) {
            return false;
        }
    }

    private boolean storageReady() {
        try {
            Files.createDirectories(storageRoot);
            Path probe = Files.createTempFile(storageRoot, ".readiness-", ".tmp");
            try {
                Files.writeString(probe, "ready");
            } finally {
                Files.deleteIfExists(probe);
            }
            return true;
        } catch (IOException | SecurityException exception) {
            return false;
        }
    }

    public record HealthView(String status, String database, String storage) {}

    private static final class NotReady extends RuntimeException {
        private final HealthView view;

        private NotReady(HealthView view) {
            this.view = view;
        }
    }
}
