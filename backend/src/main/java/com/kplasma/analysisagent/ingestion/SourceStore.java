package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.UploadManifest;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.text.Normalizer;
import java.util.*;
import java.util.zip.CRC32;
import java.util.zip.CheckedInputStream;
import org.apache.commons.compress.archivers.zip.ZipFile;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Streams original bytes into an isolated staging directory. No parser or Run activation occurs here. */
@Component
public class SourceStore {
    public record Limits(int files, long fileBytes, long totalBytes) {}
    public static final Limits DEFAULT_LIMITS = new Limits(5000, 64L * 1024 * 1024, 2L * 1024 * 1024 * 1024);
    private final Path root;
    private final Limits limits;
    @Autowired public SourceStore(@Value("${kplasma.storage-root}") String root) { this(Path.of(root)); }
    public SourceStore(Path root) { this(root, DEFAULT_LIMITS); }
    SourceStore(Path root, Limits limits) { this.root = root.toAbsolutePath().normalize(); this.limits = limits; }
    public Path root() { return root; }

    public StoredBatch stage(UploadManifest manifest, List<UploadPart> parts) {
        Path staging = null;
        try {
            validateManifest(manifest, parts);
            Path stagingParent = safeDirectory(root.resolve("staging"));
            UUID id = UUID.randomUUID();
            staging = Files.createDirectory(stagingParent.resolve(id.toString()));
            List<StoredBatch.File> files = new ArrayList<>();
            Set<String> paths = new HashSet<>();
            long[] total = {0}; long received;
            Map<String, UploadPart> byName = new HashMap<>();
            for (var part : parts) {
                if (!Files.isRegularFile(part.path(), LinkOption.NOFOLLOW_LINKS)) throw IntakeException.invalid("Upload must be a regular file");
                byName.put(part.partName(), part);
            }
            if ("FOLDER".equals(manifest.mode())) {
                for (var entry : manifest.entries()) {
                    String path = safeRelativePath(entry.relativePath());
                    try (var input = Files.newInputStream(byName.get(entry.partName()).path(), LinkOption.NOFOLLOW_LINKS)) {
                        files.add(copy(input, staging, path, paths, total));
                    }
                }
                received = total[0];
            } else {
                var archive = parts.getFirst();
                received = countArchive(archive.path());
                ZipDirectoryBounds.verify(archive.path());
                try (var zip = ZipFile.builder().setPath(archive.path()).get()) {
                    var entries = zip.getEntries();
                    Set<String> directoryPaths = new HashSet<>();
                    while (entries.hasMoreElements()) {
                        var entry = entries.nextElement();
                        if (entry.isUnixSymlink() || ((entry.getUnixMode() & 0170000) != 0 && (entry.getUnixMode() & 0170000) != 0100000 && (entry.getUnixMode() & 0170000) != 0040000))
                            throw IntakeException.invalid("ZIP links and special files are not supported");
                        String name = entry.getName();
                        if (entry.isDirectory() && name.endsWith("/")) name = name.substring(0, name.length() - 1);
                        String path = safeRelativePath(name);
                        if (entry.isDirectory()) {
                            checkDirectory(path, paths, directoryPaths); continue;
                        }
                        if (!zip.canReadEntryData(entry)) throw IntakeException.invalid("Unsupported ZIP entry encoding");
                        if (directoryPaths.contains(collisionKey(path))) throw IntakeException.invalid("Conflicting upload paths");
                        CRC32 crc = new CRC32();
                        try (var input = new CheckedInputStream(zip.getInputStream(entry), crc)) {
                            var file = copy(input, staging, path, paths, total);
                            if (crc.getValue() != entry.getCrc() || file.size() != entry.getSize()) throw IntakeException.invalid("Corrupt ZIP entry");
                            files.add(file);
                        }
                    }
                }
                if (files.isEmpty()) throw IntakeException.invalid("Archive contains no files");
            }
            return new StoredBatch(id, staging, files, total[0], received);
        } catch (IntakeException e) {
            cleanup(staging); throw e;
        } catch (IOException e) {
            cleanup(staging); throw IntakeException.invalid("Cannot read or store original upload");
        } catch (RuntimeException e) {
            cleanup(staging); throw e;
        } finally {
            if (parts != null) for (var part : parts) if (part != null && part.path() != null) cleanup(part.path());
        }
    }
    private void validateManifest(UploadManifest manifest, List<UploadPart> parts) {
        if (manifest == null || manifest.entries() == null || manifest.entries().isEmpty() || parts == null)
            throw IntakeException.invalid("A manifest and file parts are required");
        if (!"FOLDER".equals(manifest.mode()) && !"ZIP".equals(manifest.mode())) throw IntakeException.invalid("mode must be FOLDER or ZIP");
        if (manifest.entries().size() > limits.files()) throw IntakeException.limit("Too many files");
        if ("ZIP".equals(manifest.mode()) && manifest.entries().size() != 1) throw IntakeException.invalid("ZIP requires one archive part");
        Set<String> expected = new HashSet<>();
        for (var entry : manifest.entries()) {
            if (entry == null || entry.partName() == null || entry.partName().isBlank() || "manifest".equals(entry.partName()) || !expected.add(entry.partName()))
                throw IntakeException.invalid("Duplicate or invalid part name");
            safeRelativePath(entry.relativePath());
        }
        Set<String> actual = new HashSet<>();
        for (var part : parts) if (part == null || !actual.add(part.partName())) throw IntakeException.invalid("Duplicate file part");
        if (!actual.equals(expected)) throw IntakeException.invalid("File parts do not match manifest");
    }
    private StoredBatch.File copy(InputStream input, Path staging, String relative, Set<String> paths, long[] total) throws IOException {
        if (paths.size() >= limits.files()) throw IntakeException.limit("Too many files");
        String key = collisionKey(relative);
        if (!paths.add(key)) throw IntakeException.invalid("Conflicting upload paths");
        for (String path : paths) if (!path.equals(key) && (path.startsWith(key + "/") || key.startsWith(path + "/")))
            throw IntakeException.invalid("Conflicting upload paths");
        Path target = staging.resolve(relative);
        Files.createDirectories(target.getParent());
        long size = 0; MessageDigest digest = digest();
        try (var output = Files.newOutputStream(target, StandardOpenOption.CREATE_NEW)) {
            byte[] buffer = new byte[64 * 1024]; int read;
            while ((read = input.read(buffer)) != -1) {
                size += read; total[0] += read;
                if (size > limits.fileBytes()) throw IntakeException.limit("File exceeds size limit");
                if (total[0] > limits.totalBytes()) throw IntakeException.limit("Upload exceeds total byte limit");
                digest.update(buffer, 0, read); output.write(buffer, 0, read);
            }
        }
        return new StoredBatch.File(relative, target, size, HexFormat.of().formatHex(digest.digest()), kind(relative));
    }
    private long countArchive(Path path) throws IOException {
        long bytes = 0;
        try (var input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer = new byte[64 * 1024]; int read;
            while ((read = input.read(buffer)) != -1) { bytes += read; if (bytes > limits.totalBytes()) throw IntakeException.limit("Archive exceeds container byte limit"); }
        }
        return bytes;
    }
    static String safeRelativePath(String path) {
        if (path == null || path.isBlank() || path.length() > 1024 || path.startsWith("/") || path.contains("\\") || path.contains(":"))
            throw IntakeException.invalid("Invalid relative path");
        for (int i = 0; i < path.length(); i++) if (Character.isISOControl(path.charAt(i))) throw IntakeException.invalid("Invalid relative path");
        for (String segment : path.split("/", -1)) if (segment.isEmpty() || segment.equals(".") || segment.equals("..") || segment.endsWith(".") || segment.endsWith(" "))
            throw IntakeException.invalid("Invalid relative path");
        return path;
    }
    // Be conservative on case-insensitive and Unicode-normalizing storage filesystems.
    private static String collisionKey(String path) { return Normalizer.normalize(path, Normalizer.Form.NFC).toLowerCase(Locale.ROOT); }
    private static void checkDirectory(String path, Set<String> files, Set<String> directories) {
        String key = collisionKey(path);
        for (var file : files) if (file.equals(key) || key.startsWith(file + "/")) throw IntakeException.invalid("Conflicting upload paths");
        directories.add(key);
    }
    Path safeDirectory(Path path) throws IOException {
        Path absolute = path.toAbsolutePath().normalize();
        if (!absolute.startsWith(root)) throw IntakeException.invalid("Invalid storage location");
        // The configured root is trusted; system ancestors such as macOS /var may be aliases.
        // Uploaded paths and every directory below the root must never follow a link.
        if (Files.isSymbolicLink(root)) throw IntakeException.invalid("Storage symlink is not permitted");
        Files.createDirectories(root);
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS)) throw IntakeException.invalid("Storage directory unavailable");
        Path current = root;
        for (var segment : root.relativize(absolute)) {
            if (segment.toString().isEmpty()) continue;
            current = current.resolve(segment);
            if (Files.isSymbolicLink(current)) throw IntakeException.invalid("Storage symlink is not permitted");
            if (!Files.exists(current, LinkOption.NOFOLLOW_LINKS)) Files.createDirectory(current);
            if (!Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) throw IntakeException.invalid("Storage directory unavailable");
        }
        return absolute;
    }
    static boolean operatingSystemMetadata(String path) {
        for (String segment : path.split("/")) if (segment.equals(".DS_Store") || segment.equals("__MACOSX") || segment.startsWith("._") || segment.equals("Thumbs.db")) return true;
        return false;
    }
    static String kind(String path) {
        if (path.endsWith("0d_setting.ini")) return "SETTING";
        if (path.endsWith(".log")) return "LOG";
        for (String kind : List.of("IED", "IAD", "IEAD", "CUR", "POT", "DEN")) if (path.contains("/" + kind + "/")) return kind;
        return "OTHER";
    }
    static MessageDigest digest() { try { return MessageDigest.getInstance("SHA-256"); } catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); } }
    static String hashFiles(Map<String, StoredBatch.File> files) {
        MessageDigest digest = digest();
        files.entrySet().stream().filter(e -> !operatingSystemMetadata(e.getKey())).sorted(Map.Entry.comparingByKey()).forEach(e -> {
            digest.update(e.getKey().getBytes(StandardCharsets.UTF_8)); digest.update((byte) 0);
            digest.update(e.getValue().sha256().getBytes(StandardCharsets.US_ASCII)); digest.update((byte) '\n');
        });
        return HexFormat.of().formatHex(digest.digest());
    }
    static void cleanup(Path path) {
        if (path == null || !Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return;
        try (var paths = Files.walk(path)) {
            for (var p : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(p);
        } catch (IOException e) { throw new UncheckedIOException("Temporary storage cleanup failed", e); }
    }
}
