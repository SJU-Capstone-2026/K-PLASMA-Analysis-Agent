package com.kplasma.analysisagent.ingestion;

import com.kplasma.analysisagent.contract.ImportDto.UploadEntry;
import com.kplasma.analysisagent.contract.ImportDto.UploadManifest;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.assertj.core.api.Assertions.*;

class SourceStoreTest {
    @TempDir Path temp;
    private UploadPart part(String name, String text) throws IOException {
        Path path = Files.createTempFile(temp, "upload-", ".tmp");
        Files.writeString(path, text);
        return new UploadPart(name, path, 0); // declared sizes must never replace actual reads
    }
    private UploadPart zip(Map<String, String> contents) throws IOException {
        Path path = Files.createTempFile(temp, "upload-", ".zip");
        try (var out = new ZipOutputStream(Files.newOutputStream(path))) {
            for (var e : contents.entrySet()) {
                out.putNextEntry(new ZipEntry(e.getKey())); out.write(e.getValue().getBytes()); out.closeEntry();
            }
        }
        return new UploadPart("archive", path, 0);
    }
    private SourceStore store() { return new SourceStore(temp.resolve("store")); }
    private UploadManifest folder(String... paths) {
        List<UploadEntry> entries = new ArrayList<>();
        for (int i = 0; i < paths.length; i++) entries.add(new UploadEntry("f" + i, paths[i]));
        return new UploadManifest("FOLDER", entries);
    }
    @Test void folderAndZipHaveSameRunHashAndRetainDistinctDuplicateBasenames() throws Exception {
        var files = new LinkedHashMap<String, String>();
        files.put("whole/PRS_02/Source_100/Bias_0200/0d_setting.ini", "synthetic setting");
        files.put("whole/PRS_02/Source_100/Bias_0200/0d_result/output/IED/Ar+.txt", "IED bytes");
        files.put("whole/PRS_02/Source_100/Bias_0200/0d_result/output/IAD/Ar+.txt", "IAD bytes");
        var uploads = new ArrayList<UploadPart>();
        int n = 0; for (var text : files.values()) uploads.add(part("f" + n++, text));
        var a = store().stage(folder(files.keySet().toArray(String[]::new)), uploads);
        // Single Run packaging and unrelated hidden OS files do not alter source identity.
        var zipped = new LinkedHashMap<String, String>();
        files.forEach((path, text) -> zipped.put(path.substring(path.indexOf("0d_")), text));
        zipped.put(".DS_Store", "metadata");
        var b = store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "original.zip"))), List.of(zip(zipped)));
        var sourceA = new RunSourceDiscovery().discover(a).getFirst();
        var sourceB = new RunSourceDiscovery().discover(b).getFirst();
        assertThat(sourceA.sha256()).isEqualTo(sourceB.sha256());
        assertThat(sourceA.files()).containsKeys("0d_result/output/IED/Ar+.txt", "0d_result/output/IAD/Ar+.txt");
        assertThat(Files.readString(sourceA.files().get("0d_result/output/IED/Ar+.txt").path())).isEqualTo("IED bytes");
        assertThat(a.totalBytes()).isEqualTo(35);
        for (var upload : uploads) assertThat(upload.path()).doesNotExist();
    }
    @Test void rejectsTraversalCollisionsAndCleansUploadedAndStagedBytes() throws Exception {
        for (String bad : List.of("../escape", "/absolute", "C:/drive", "a/../escape", "a\\escape", "a//b", "./a")) {
            var upload = part("f0", "bytes");
            assertThatThrownBy(() -> store().stage(folder(bad), List.of(upload))).isInstanceOf(IntakeException.class);
            assertThat(upload.path()).doesNotExist();
        }
        var one = part("f0", "one"); var two = part("f1", "two");
        assertThatThrownBy(() -> store().stage(folder("same", "same"), List.of(one, two))).isInstanceOf(IntakeException.class);
        assertThat(one.path()).doesNotExist(); assertThat(two.path()).doesNotExist();
        if (Files.exists(temp.resolve("store/staging"))) try (var roots = Files.list(temp.resolve("store/staging"))) { assertThat(roots.count()).isZero(); }
    }
    @Test void rejectsZipTraversalFileDirectoryConflictsAndInvalidArchive() throws Exception {
        for (var contents : List.of(Map.of("../escape", "bad"), Map.of("a", "file", "a/b", "child"))) {
            var archive = zip(contents);
            assertThatThrownBy(() -> store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(archive))).isInstanceOf(IntakeException.class);
            assertThat(archive.path()).doesNotExist();
        }
        var invalid = part("archive", "not a zip");
        assertThatThrownBy(() -> store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(invalid))).isInstanceOf(IntakeException.class);
    }
    @Test void limitsUseActualBytesAndRejectCountAndExpandedTotals() throws Exception {
        var small = new SourceStore(temp.resolve("small"), new SourceStore.Limits(2, 4, 8));
        assertThatThrownBy(() -> small.stage(folder("a"), List.of(part("f0", "12345")))).isInstanceOf(IntakeException.class);
        assertThatThrownBy(() -> small.stage(folder("a", "b", "c"), List.of(part("f0", "1"), part("f1", "2"), part("f2", "3")))).isInstanceOf(IntakeException.class);
        var bounded = new SourceStore(temp.resolve("bounded"), new SourceStore.Limits(10, 4, 8));
        assertThatThrownBy(() -> bounded.stage(folder("a", "b", "c"), List.of(part("f0", "1234"), part("f1", "1234"), part("f2", "1")))).isInstanceOf(IntakeException.class);
        var bomb = zip(Map.of("a", "12345"));
        assertThatThrownBy(() -> small.stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(bomb))).isInstanceOf(IntakeException.class);
    }
    @Test void archiveContainerMayExceedPerFileLimitButExpandedFilesMayNot() throws Exception {
        var bounded = new SourceStore(temp.resolve("bounded"), new SourceStore.Limits(10, 4, 1024));
        var archive = zip(Map.of("0d_setting.ini", "1234", "other", "1234"));
        assertThat(Files.size(archive.path())).isGreaterThan(4);
        var result = bounded.stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "original.zip"))), List.of(archive));
        assertThat(result.totalBytes()).isEqualTo(8);
        assertThat(result.files()).hasSize(2);
    }
    @Test void rejectsSymlinkUploadsAndStorageEscape() throws Exception {
        Path outside = Files.writeString(temp.resolve("outside"), "secret");
        Path link = Files.createSymbolicLink(temp.resolve("link"), outside);
        assertThatThrownBy(() -> store().stage(folder("0d_setting.ini"), List.of(new UploadPart("f0", link, 6)))).isInstanceOf(IntakeException.class);
        Files.createDirectories(temp.resolve("escape-store"));
        Files.createSymbolicLink(temp.resolve("escape-store/staging"), temp.resolve("escaped"));
        Files.createDirectories(temp.resolve("escaped"));
        assertThatThrownBy(() -> new SourceStore(temp.resolve("escape-store")).stage(folder("0d_setting.ini"), List.of(part("f0", "input")))).isInstanceOf(IntakeException.class);
        assertThat(Files.readString(outside)).isEqualTo("secret");
        try (var entries = Files.list(temp.resolve("escaped"))) { assertThat(entries.count()).isZero(); }
    }
    @Test void rejectsCorruptedEntryEvenIfItDecompresses() throws Exception {
        Path path = Files.createTempFile(temp, "corrupt-", ".zip");
        byte[] payload = "original bytes".getBytes();
        CRC32 crc = new CRC32(); crc.update(payload);
        try (var output = new ZipOutputStream(Files.newOutputStream(path))) {
            var entry = new ZipEntry("0d_setting.ini"); entry.setMethod(ZipEntry.STORED);
            entry.setSize(payload.length); entry.setCrc(crc.getValue());
            output.putNextEntry(entry); output.write(payload); output.closeEntry();
        }
        byte[] archive = Files.readAllBytes(path);
        archive[30 + "0d_setting.ini".length()] ^= 1; Files.write(path, archive);
        assertThatThrownBy(() -> store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(new UploadPart("archive", path, archive.length)))).isInstanceOf(IntakeException.class);
        assertThat(path).doesNotExist();
    }
    @Test void rejectsZipSymlinksDuplicateEntriesAndUnicodeCaseCollisions() throws Exception {
        Path link = Files.createTempFile(temp, "link-", ".zip");
        try (var out = new org.apache.commons.compress.archivers.zip.ZipArchiveOutputStream(link)) {
            var entry = new org.apache.commons.compress.archivers.zip.ZipArchiveEntry("link");
            entry.setUnixMode(0120777); out.putArchiveEntry(entry); out.write("../outside".getBytes()); out.closeArchiveEntry();
        }
        assertThatThrownBy(() -> store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(new UploadPart("archive", link, 0)))).isInstanceOf(IntakeException.class);
        Path duplicate = Files.createTempFile(temp, "duplicate-", ".zip");
        try (var out = new org.apache.commons.compress.archivers.zip.ZipArchiveOutputStream(duplicate)) {
            for (int i = 0; i < 2; i++) { out.putArchiveEntry(new org.apache.commons.compress.archivers.zip.ZipArchiveEntry("same")); out.write('x'); out.closeArchiveEntry(); }
        }
        assertThatThrownBy(() -> store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(new UploadPart("archive", duplicate, 0)))).isInstanceOf(IntakeException.class);
        for (String[] paths : List.of(new String[]{"Case.txt", "case.txt"}, new String[]{"é.txt", "é.txt"})) {
            assertThatThrownBy(() -> store().stage(folder(paths), List.of(part("f0", "a"), part("f1", "b")))).isInstanceOf(IntakeException.class);
        }
    }
    @Test void rejectsExpandedZipTotalIndependentlyOfContainerAndPerEntryLimits() throws Exception {
        var archive = zip(Map.of("a", "x".repeat(200), "b", "y".repeat(200)));
        assertThat(Files.size(archive.path())).isLessThan(300);
        var bounded = new SourceStore(temp.resolve("expanded"), new SourceStore.Limits(2, 256, 300));
        assertThatThrownBy(() -> bounded.stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(archive))).isInstanceOf(IntakeException.class).hasMessageContaining("total byte");
        var tooLargeEntry = zip(Map.of("a", "x".repeat(300)));
        assertThatThrownBy(() -> new SourceStore(temp.resolve("entry"), new SourceStore.Limits(2, 256, 1024)).stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(tooLargeEntry))).isInstanceOf(IntakeException.class).hasMessageContaining("File exceeds");
    }
    @Test void actualDefaultArchiveExceeds64MiBWithoutRejectingItsSmallEntries() throws Exception {
        Path archive = Files.createTempFile(temp, "large-", ".zip");
        try (var out = new ZipOutputStream(Files.newOutputStream(archive))) {
            byte[] chunk = new byte[1024 * 1024]; new Random(47).nextBytes(chunk);
            for (int n = 0; n < 65; n++) {
                out.putNextEntry(new ZipEntry(n == 0 ? "0d_setting.ini" : "auxiliary/" + n + ".txt"));
                out.write(chunk); out.closeEntry();
            }
        }
        assertThat(Files.size(archive)).isGreaterThan(64L * 1024 * 1024);
        var batch = store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(new UploadPart("archive", archive, 0)));
        assertThat(batch.totalBytes()).isEqualTo(65L * 1024 * 1024);
        assertThat(batch.files()).hasSize(65);
    }

    @Test void rejectsExhaustingZipMetadataSeparatelyFromFileLimit() throws Exception {
        Path archive = Files.createTempFile(temp, "metadata-", ".zip");
        try (var out = new org.apache.commons.compress.archivers.zip.ZipArchiveOutputStream(archive)) {
            for (int i = 0; i < 400; i++) {
                var entry = new org.apache.commons.compress.archivers.zip.ZipArchiveEntry("directory-" + i + "/");
                entry.setComment("c".repeat(60_000)); out.putArchiveEntry(entry); out.closeArchiveEntry();
            }
            out.putArchiveEntry(new org.apache.commons.compress.archivers.zip.ZipArchiveEntry("0d_setting.ini")); out.write('x'); out.closeArchiveEntry();
        }
        assertThatThrownBy(() -> store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(new UploadPart("archive", archive, 0))))
                .isInstanceOf(IntakeException.class).hasMessageContaining("metadata");
    }

    @Test void acceptsManyDirectoryEntriesAndZip64WithoutCountingThemAsOrdinaryFiles() throws Exception {
        Path archive = Files.createTempFile(temp, "directories-", ".zip");
        try (var out = new org.apache.commons.compress.archivers.zip.ZipArchiveOutputStream(archive)) {
            out.setUseZip64(org.apache.commons.compress.archivers.zip.Zip64Mode.Always);
            for (int i = 0; i < 21_000; i++) { out.putArchiveEntry(new org.apache.commons.compress.archivers.zip.ZipArchiveEntry("d" + i + "/")); out.closeArchiveEntry(); }
            out.putArchiveEntry(new org.apache.commons.compress.archivers.zip.ZipArchiveEntry("0d_setting.ini")); out.write('x'); out.closeArchiveEntry();
        }
        var result = store().stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(new UploadPart("archive", archive, 0)));
        assertThat(result.files()).hasSize(1);
        assertThat(result.totalBytes()).isEqualTo(1);
    }
    @Test void rejectsZipFileCountAboveLimit() throws Exception {
        var archive = zip(Map.of("a", "x", "b", "y", "c", "z"));
        var bounded = new SourceStore(temp.resolve("count"), new SourceStore.Limits(2, 64, 1024));
        assertThatThrownBy(() -> bounded.stage(new UploadManifest("ZIP", List.of(new UploadEntry("archive", "a.zip"))), List.of(archive))).isInstanceOf(IntakeException.class).hasMessageContaining("Too many files");
    }

}
