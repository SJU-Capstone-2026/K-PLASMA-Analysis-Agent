# Synthetic parser fixtures

`parser/ScalarParserTest` writes small artificial INI, solver, completion and residual files into JUnit temporary storage. The numbers are chosen to expose unit conversion, source-section identity, final residual-column handling and strict-threshold equality. They are not real physical results and never appear in product seed data.

The tests cover decimal/scientific notation, inline `#` comments, the exact known `BiasPower.rfCycle` U+0001 token, unknown control characters, contradictory conditions, unsupported release/species/pulsing, duplicate INI keys, incorrect units, malformed/nonfinite values, missing files and missing completion evidence. Bias-off deliberately lacks both solver bias sections and distribution outputs.

External baseline comparisons require a separately supplied reference package. Do not place raw Run files, `analysis-data.js`, expected real scalars or graphs here. Keep real-data test output in ignored local runtime storage.
