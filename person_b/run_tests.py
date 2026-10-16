import sys, importlib, traceback
mods = sys.argv[1:]
skip = {"test_leaving_free_space_is_flagged", "test_hub_must_be_inside_a_room_and_half_a_metre_from_walls"} if "--skip-geom" in mods else set()
mods = [m for m in mods if not m.startswith("--")]
ok = bad = 0
for m in mods:
    mod = importlib.import_module(m)
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        if name in skip:
            print("SKIP", m, name); continue
        try:
            getattr(mod, name)(); ok += 1; print("PASS", m, name)
        except Exception:
            bad += 1; print("FAIL", m, name); traceback.print_exc()
print(f"\n{ok} passed, {bad} failed")
