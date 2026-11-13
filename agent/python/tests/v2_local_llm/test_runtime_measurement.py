import importlib


def test_memory_measurement_parses_pressure_swap_and_resident_pages_without_estimating_from_weight_sizes():
    name = "kplasma_agent.v2_local_llm.runtime"
    assert importlib.util.find_spec(name), "native memory sampling is missing"
    parse = importlib.import_module(name).parse_memory_sample
    result = parse("vm.swapusage: total = 8192.00M  used = 1024.50M  free = 7167.50M\n"
                   "kern.memorystatus_vm_pressure_level: 2\n",
                   "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                   "Pages active: 10.\nPages wired down: 20.\nPages occupied by compressor: 5.\n")
    assert result == {"pressure": 2, "swap_bytes": 1074266112, "resident_bytes": 573440}
