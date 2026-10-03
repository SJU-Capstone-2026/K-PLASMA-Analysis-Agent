package com.kplasma.analysisagent.parser;

/** Select original indices with exact rational half-even rounding, including both endpoints. */
public final class SourceGridSampler {
    private SourceGridSampler() {}
    public static int[] sampleIndices(int n, int maxPoints) {
        if (n <= 0 || maxPoints <= 0 || n > 1 && maxPoints == 1)
            throw new IllegalArgumentException("Positive source and room for both endpoints required");
        int m = Math.min(n, maxPoints);
        int[] indices = new int[m];
        if (m == 1) return indices;
        long denominator = m - 1L;
        for (int i = 0; i < m; i++) {
            long numerator = (long) i * (n - 1L);
            long quotient = numerator / denominator, remainder = numerator % denominator;
            if (2 * remainder > denominator || 2 * remainder == denominator && quotient % 2 != 0) quotient++;
            indices[i] = (int) quotient;
        }
        return indices;
    }
}
