package com.kplasma.analysisagent.health;

import com.jayway.jsonpath.JsonPath;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class StartupSmokeTest {
    @Container
    static final PostgreSQLContainer DATABASE = new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path TEMP_ROOT = temporaryDirectory();
    static final Path STORAGE = TEMP_ROOT.resolve("storage");

    @LocalServerPort
    int port;

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", DATABASE::getJdbcUrl);
        registry.add("spring.datasource.username", DATABASE::getUsername);
        registry.add("spring.datasource.password", DATABASE::getPassword);
        registry.add("kplasma.storage-root", STORAGE::toString);
        registry.add("spring.datasource.hikari.connection-timeout", () -> 1000);
        registry.add("spring.datasource.hikari.validation-timeout", () -> 500);
    }

    @BeforeEach
    void prepareStorage() throws IOException {
        deleteTree(STORAGE);
        Files.createDirectories(STORAGE);
    }

    @Test
    @Order(1)
    void readyDatabaseAndStorageReturnUp() throws Exception {
        var response = health();
        assertThat(response.statusCode()).isEqualTo(200);
        assertThat(JsonPath.<String>read(response.body(), "$.status")).isEqualTo("UP");
        assertThat(JsonPath.<String>read(response.body(), "$.database")).isEqualTo("UP");
        assertThat(JsonPath.<String>read(response.body(), "$.storage")).isEqualTo("UP");
    }

    @Test
    @Order(2)
    void unavailableStorageReturnsServiceUnavailable() throws Exception {
        Files.delete(STORAGE);
        Files.writeString(STORAGE, "A file cannot be used as a storage directory");
        var response = health();
        assertThat(response.statusCode()).isEqualTo(503);
        assertThat(JsonPath.<String>read(response.body(), "$.status")).isEqualTo("DOWN");
        assertThat(JsonPath.<String>read(response.body(), "$.database")).isEqualTo("UP");
        assertThat(JsonPath.<String>read(response.body(), "$.storage")).isEqualTo("DOWN");
    }

    @Test
    @Order(3)
    void missingStorageIsPreparedWithoutRemovingExistingData() throws Exception {
        Files.delete(STORAGE);
        assertThat(health().statusCode()).isEqualTo(200);
        assertThat(Files.isDirectory(STORAGE)).isTrue();
        Path existingSource = STORAGE.resolve("existing-source.txt");
        Files.writeString(existingSource, "synthetic retained source");
        assertThat(health().statusCode()).isEqualTo(200);
        assertThat(Files.readString(existingSource)).isEqualTo("synthetic retained source");
        try (var entries = Files.list(STORAGE)) {
            assertThat(entries.toList()).containsExactly(existingSource);
        }
    }

    @Test
    @Order(4)
    void databaseOutageReturnsServiceUnavailable() throws Exception {
        DATABASE.stop();
        var response = health();
        assertThat(response.statusCode()).isEqualTo(503);
        assertThat(JsonPath.<String>read(response.body(), "$.status")).isEqualTo("DOWN");
        assertThat(JsonPath.<String>read(response.body(), "$.database")).isEqualTo("DOWN");
        assertThat(JsonPath.<String>read(response.body(), "$.storage")).isEqualTo("UP");
    }

    private HttpResponse<String> health() throws Exception {
        try (var client = HttpClient.newHttpClient()) {
            return client.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/health"))
                    .GET().build(), HttpResponse.BodyHandlers.ofString());
        }
    }

    @AfterAll
    static void cleanUp() throws IOException {
        deleteTree(TEMP_ROOT);
    }

    private static Path temporaryDirectory() {
        try {
            return Files.createTempDirectory("kplasma-smoke-");
        } catch (IOException exception) {
            throw new ExceptionInInitializerError(exception);
        }
    }

    private static void deleteTree(Path root) throws IOException {
        if (Files.exists(root)) {
            try (var paths = Files.walk(root)) {
                for (var path : paths.sorted(Comparator.reverseOrder()).toList()) {
                    Files.delete(path);
                }
            }
        }
    }
}
