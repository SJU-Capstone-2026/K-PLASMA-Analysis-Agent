package com.kplasma.analysisagent.ingestion;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Path;

/** Bounds the central directory before Commons Compress allocates entry objects or extra fields. */
final class ZipDirectoryBounds {
    static final long METADATA_BUDGET = 16L * 1024 * 1024;
    private ZipDirectoryBounds() {}

    static void verify(Path path) throws IOException {
        try (var file = new RandomAccessFile(path.toFile(), "r")) {
            long length = file.length();
            if (length < 22) throw IntakeException.invalid("Invalid ZIP directory");
            int tailLength = (int) Math.min(length, 22 + 65535);
            byte[] tail = read(file, length - tailLength, tailLength).array();
            ByteBuffer end = ByteBuffer.wrap(tail).order(ByteOrder.LITTLE_ENDIAN);
            int index = -1;
            for (int i = tailLength - 22; i >= 0; i--) {
                if (end.getInt(i) == 0x06054b50 && i + 22 + unsignedShort(end, i + 20) == tailLength) { index = i; break; }
            }
            if (index < 0) throw IntakeException.invalid("Invalid ZIP directory");
            long endOffset = length - tailLength + index;
            if (unsignedShort(end, index + 4) != 0 || unsignedShort(end, index + 6) != 0 || unsignedShort(end, index + 8) != unsignedShort(end, index + 10))
                throw IntakeException.invalid("Multi-disk ZIP is not supported");
            long count = unsignedShort(end, index + 10);
            long centralSize = Integer.toUnsignedLong(end.getInt(index + 12));
            long centralOffset = Integer.toUnsignedLong(end.getInt(index + 16));
            if (endOffset >= 20 && read(file, endOffset - 20, 4).getInt(0) == 0x07064b50) {
                ByteBuffer locator = read(file, endOffset - 20, 20);
                if (locator.getInt(4) != 0 || locator.getInt(16) != 1) throw IntakeException.invalid("Multi-disk ZIP is not supported");
                long zip64Offset = locator.getLong(8);
                if (zip64Offset < 0 || zip64Offset > endOffset - 76) throw IntakeException.invalid("Invalid ZIP64 directory");
                ByteBuffer zip64 = read(file, zip64Offset, 56);
                if (zip64.getInt(0) != 0x06064b50 || zip64.getLong(4) < 44 || zip64.getInt(16) != 0 || zip64.getInt(20) != 0 || zip64.getLong(24) != zip64.getLong(32))
                    throw IntakeException.invalid("Invalid ZIP64 directory");
                count = zip64.getLong(32); centralSize = zip64.getLong(40); centralOffset = zip64.getLong(48);
                endOffset = zip64Offset;
            } else if (count == 0xffff || centralSize == 0xffffffffL || centralOffset == 0xffffffffL) {
                throw IntakeException.invalid("Missing ZIP64 directory");
            }
            if (count < 0 || centralSize < 0 || centralOffset < 0 || centralOffset > endOffset || centralSize > endOffset - centralOffset)
                throw IntakeException.invalid("Invalid ZIP directory bounds");
            if (centralSize > METADATA_BUDGET) throw metadataLimit();
            long cursor = centralOffset, centralEnd = centralOffset + centralSize;
            long entries = 0, budget = 22 + unsignedShort(end, index + 20);
            while (cursor < centralEnd) {
                if (centralEnd - cursor < 46) throw IntakeException.invalid("Truncated ZIP directory");
                ByteBuffer header = read(file, cursor, 46);
                if (header.getInt(0) != 0x02014b50) throw IntakeException.invalid("Invalid ZIP directory entry");
                int nameLength = unsignedShort(header, 28), extraLength = unsignedShort(header, 30), commentLength = unsignedShort(header, 32);
                long recordLength = 46L + nameLength + extraLength + commentLength;
                if (recordLength > centralEnd - cursor) throw IntakeException.invalid("Truncated ZIP directory entry");
                // Account for serialized metadata and fixed per-entry object/index overhead.
                budget += recordLength + 256;
                if (budget > METADATA_BUDGET) throw metadataLimit();
                if (++entries > count) throw IntakeException.invalid("Invalid ZIP directory count");
                cursor += recordLength;
            }
            if (entries != count) throw IntakeException.invalid("Invalid ZIP directory count");
        }
    }
    private static IntakeException metadataLimit() { return new IntakeException("ZIP_METADATA_LIMIT_EXCEEDED", 413, "ZIP metadata exceeds bounded allocation budget"); }
    private static int unsignedShort(ByteBuffer buffer, int offset) { return Short.toUnsignedInt(buffer.getShort(offset)); }
    private static ByteBuffer read(RandomAccessFile file, long offset, int length) throws IOException {
        byte[] bytes = new byte[length]; file.seek(offset); file.readFully(bytes);
        return ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
    }
}
