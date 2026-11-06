package com.kplasma.analysisagent.ingestion;
import java.util.HashMap;
import java.util.Map;
/** Entirely artificial parser inputs shared by pipeline integration tests. */
public final class SyntheticRunFiles {
    public static Map<String,String> files(String marker) {
        return Map.of("0d_setting.ini",ini(false)+"# "+marker+"\n", "0d_result/log/solver.log",solver(false),
                "0d_result/log/residual.log",residual(),"0d_result/log/output.log","INFO: Finished!\n");
    }
    public static Map<String,String> biasOnFiles(String marker) {
        var files = new HashMap<>(files(marker));
        files.put("0d_setting.ini", ini(true) + "# " + marker + "\n");
        files.put("0d_result/log/solver.log", solver(true));
        files.put("0d_result/output/IED/Ar+.txt", graph("IEDs", "1D", "energy (eV)", "IED (a.u.)", 3, 0) + "0 1\n1 2\n2 1\n");
        var iad = new StringBuilder(graph("IADs", "1D", "angle (degrees)", "IAD (a.u.)", 201, 0));
        for (int i = 0; i < 201; i++) iad.append(i).append(' ').append(i == 101 ? 9 : 1).append('\n');
        files.put("0d_result/output/IAD/Ar+.txt", iad.toString());
        files.put("0d_result/output/IEAD/Ar+.txt", graph("IEAD", "2D", "angle (degrees)", "energy (eV)", 2, 2)
            + "0 0 1\n0 1 2\n1 0 1\n1 1 2\n");
        files.put("0d_result/output/CUR/J0h_h.txt", graph("Current_density", "1D", "time (rf cycle)", "J0h_h (statampere/cm^2)", 2, 0) + "0 1\n1 2\n");
        files.put("0d_result/output/POT/pot.txt", graph("Pot", "1D", "time (rf cycle)", "pot (V)", 2, 0) + "0 1\n1 2\n");
        var density = new StringBuilder(graph("DENSITY", "2D", "time (rf cycle)", "distance (cm)", 2, 31));
        for (int x = 0; x < 2; x++) for (int y = 0; y < 31; y++) density.append(x).append(' ').append(y).append(" 1\n");
        files.put("0d_result/output/DEN/Ar+.txt", density.toString());
        return files;
    }

    private static String graph(String type, String shape, String x, String y, int nx, int ny) {
        return "# type=" + type + "\n# gtype=" + shape + "\n# x=" + x + "\n# y=" + y + "\n# nx=" + nx + "\n"
            + (ny > 0 ? "# ny=" + ny + "\n" : "");
    }
    public static String ini(boolean bias) {
        return """
            # entirely artificial conditions and values
            [DataFile]
            reaction_path=rate_Ar.xml
            unrelated=
            [Option]
            solver=2
            conv=1.e-2 # threshold
            [Pressure]
            PRS=2
            key0=Ar
            [SourcePower]
            Heat=1
            Powerh=1.e2
            Pulsing=0
            [BiasPower]
            Bias=%s
            Sourceh0=%s
            Pulsing0=0
            rfCycle=%s
            """.formatted(bias ? "1" : "0", bias ? "2.e2" : "0", "\u0001");
    }
    public static String solver(boolean bias) {
        return """
            RELEASE 8.8.1, synthetic
            [SIMULATION OPTIONS]
            Source = TCP
            Heating = ON
            SPulsing = OFF
            Bias = %s
            [SOURCE POWER CONDITIONS]
            PowerH = 1.e2 (W)
            %s
            [PREASURE & INLET CONDITIONS]
            Pressure = 2 (mTorr)
            Inlet species = Ar
            [TEMPERATURE PARAMETERS]
            Gas Temp. = 0.03 (eV)
            Electron Temp. = 3.5 (eV)
            Ion Temp. = 0.25 (eV)
            [HEATING PARAMETERS]
            Absorbed power = 80 (W)
            alpha = 0.8 (a.u.)
            Plasma resistance = 0.4 (ohm)
            Plasma reactance = 8 (ohm)
            %s
            [SHEATH PARAMETERS]
            J0h_h = 0 (statampere/cm^2)
            [NUMBER DENSITY]
            Species (#/cm^3)
            ------------------
            E 10
            Ar* 20
            Ar+ 30
            Ar 40
            [ION FLUX AT THE SHEATH EDGE]
            Species (#/cm^2sec)
            ------------------
            Ar+ 1.e14
            [RADICAL FLUX AT THE SHEATH EDGE]
            Species (#/cm^2sec)
            ------------------
            Ar* 60
            Ar 70
            [AVERAGE ION ENERGY AT THE SUBSTRATE]
            Species (eV)
            ------------------
            Ar+ 12.3456789 # precision retained
            """.formatted(bias ? "ON" : "OFF", bias ? "[BIAS POWER CONDITIONS]\nPower1h = 2.e2 (W)" : "",
                bias ? "[BIAS PARAMETERS]\ndc-offset = -8 (V)\npeak-to-peak = 24 (V)" : "");
    }
    public static String residual() {
        return """
            # type=residual
            # gtype=1D
            # x=iteration (#)
            # y=residual (a.u.)
            # species=E Ar* Ar+ Ar Te
            1 1e-1 0 0 0 0
            2 -1e-3 2e-3 3e-3 4e-3 -2.e-2
            """;
    }
}
