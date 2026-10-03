package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.*;
import com.kplasma.analysisagent.contract.WorkspaceDto;
import jakarta.servlet.http.HttpServletRequest;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.core.JacksonException;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.MultipartException;
import org.springframework.http.converter.HttpMessageNotReadableException;

@RestController
@RequestMapping("/api")
public class ImportController {
    private final SourceStore store;
    private final ImportIntakeService intake;
    private final ObjectMapper mapper;
    public ImportController(SourceStore store, ImportIntakeService intake, ObjectMapper mapper) { this.store = store; this.intake = intake; this.mapper = mapper; }
    @PostMapping(path = "/import-batches", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<BatchView> accept(@RequestHeader(name = "Idempotency-Key", required = false) String key, HttpServletRequest request) throws Exception {
        List<UploadPart> uploads = new ArrayList<>(); Path directory = null;
        try {
            var parts = request.getParts();
            if (parts.size() > 5001) throw IntakeException.limit("Too many multipart parts");
            if (parts.stream().filter(p -> p.getName().equals("manifest")).count() != 1) throw IntakeException.invalid("One manifest is required");
            var manifestPart = parts.stream().filter(p -> p.getName().equals("manifest")).findFirst().orElseThrow();
            if (manifestPart.getSize() > 8L * 1024 * 1024) throw IntakeException.limit("Manifest exceeds metadata byte limit");
            UploadManifest manifest;
            try (var input = manifestPart.getInputStream()) {
                manifest = mapper.readValue(input, UploadManifest.class);
            } catch (JacksonException e) { throw IntakeException.invalid("Invalid JSON upload manifest"); }
            if (manifest == null) throw IntakeException.invalid("A manifest is required");
            directory = Files.createTempDirectory(store.safeDirectory(store.root().resolve("uploads")), "request-");
            long received = 0;
            for (var part : parts) if (!part.getName().equals("manifest")) {
                Path file = Files.createTempFile(directory, "part-", ".tmp");
                uploads.add(new UploadPart(part.getName(), file, part.getSize()));
                long size = 0;
                try (var input = part.getInputStream(); var output = Files.newOutputStream(file)) {
                    byte[] buffer = new byte[64 * 1024]; int read;
                    while ((read = input.read(buffer)) != -1) {
                        size += read; received += read;
                        long fileLimit = "ZIP".equals(manifest.mode()) ? SourceStore.DEFAULT_LIMITS.totalBytes() : SourceStore.DEFAULT_LIMITS.fileBytes();
                        if (size > fileLimit || received > SourceStore.DEFAULT_LIMITS.totalBytes()) throw IntakeException.limit("Upload exceeds byte limit");
                        output.write(buffer, 0, read);
                    }
                }
            }
            return ResponseEntity.accepted().body(intake.accept(store.stage(manifest, uploads), key));
        } finally { SourceStore.cleanup(directory); }
    }
    @GetMapping("/import-batches/{id}") public BatchView get(@PathVariable String id) { return intake.get(id); }

    @RestControllerAdvice
    static class Errors {
        @ExceptionHandler(IntakeException.class) ResponseEntity<WorkspaceDto.Error> intake(IntakeException e) { return error(e.status(), e.code(), e.getMessage()); }
        @ExceptionHandler(MaxUploadSizeExceededException.class) ResponseEntity<WorkspaceDto.Error> tooLarge() { return error(413, "UPLOAD_LIMIT_EXCEEDED", "Multipart body exceeds byte limit"); }
        @ExceptionHandler({MultipartException.class, HttpMessageNotReadableException.class, org.springframework.web.multipart.support.MissingServletRequestPartException.class})
        ResponseEntity<WorkspaceDto.Error> malformed() { return error(400, "INVALID_UPLOAD", "Invalid multipart manifest or file parts"); }
        @ExceptionHandler({IOException.class, UncheckedIOException.class, org.springframework.dao.DataAccessException.class})
        ResponseEntity<WorkspaceDto.Error> unavailable() { return error(503, "INTAKE_UNAVAILABLE", "Original storage or database unavailable"); }
        private ResponseEntity<WorkspaceDto.Error> error(int status, String code, String message) { return ResponseEntity.status(status).body(new WorkspaceDto.Error(code, message, null, null, UUID.randomUUID().toString())); }
    }
}
