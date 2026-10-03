package com.kplasma.analysisagent.ingestion;
import java.util.Map;
/** Entirely artificial parser inputs shared by pipeline integration tests. */
public final class SyntheticRunFiles {
    public static Map<String,String> files(String marker) {
        return Map.of("0d_setting.ini",ini(false)+"# "+marker+"\n", "0d_result/log/solver.log",solver(false),
                "0d_result/log/residual.log",residual(),"0d_result/log/output.log","INFO: Finished!\n");
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
