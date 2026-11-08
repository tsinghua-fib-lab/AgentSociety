"""Owned-file regressions for public aliases that bypassed private-name checks."""

import pickle

import pytest

from agentsociety2.env.router_codegen import CodeGenRouter, CodeStage


def instance():
    return CodeGenRouter(env_modules=[], final_summary_enabled=False)


async def test_numpy_pickle_loader_cannot_execute_owned_payload(tmp_path):
    marker = tmp_path / "owned-marker.txt"

    class OwnedProof:
        def __reduce__(self):
            return (
                eval,
                (
                    f'__import__("pathlib").Path({str(marker)!r}).write_text("controlled proof only")',
                ),
            )

    payload = tmp_path / "owned.pkl"
    payload.write_bytes(pickle.dumps(OwnedProof()))
    result = await CodeStage._execute_code(
        instance(),
        "np.load(ctx['payload'], allow_pickle=True)\nresults['status'] = 'success'",
        {"payload": str(payload)},
        True,
    )
    assert not result["success"]
    assert "forbidden" in result["error"]
    assert not marker.exists()


@pytest.mark.parametrize(
    "source",
    [
        "results['value'] = np.fromfile(ctx['path'], dtype=np.uint8).tobytes().decode()\nresults['status'] = 'success'",
        "file = json.codecs.open(ctx['path'], 'r')\nresults['value'] = file.read()\nfile.close()\nresults['status'] = 'success'",
        "from json import codecs as reader\nfile = reader.open(ctx['path'], 'r')\nresults['value'] = file.read()\nfile.close()\nresults['status'] = 'success'",
        "from numpy import load as reader\nresults['value'] = reader(ctx['path'])\nresults['status'] = 'success'",
    ],
)
async def test_public_file_read_aliases_are_blocked(tmp_path, source):
    path = tmp_path / "owned-data.txt"
    path.write_text("owned synthetic data")
    result = await CodeStage._execute_code(
        instance(), source, {"path": str(path)}, True
    )
    assert not result["success"]
    assert "forbidden" in result["error"] or "not allowed" in result["error"]
    assert result.get("results", {}).get("value") != "owned synthetic data"


@pytest.mark.parametrize(
    "source",
    [
        "np.save(ctx['path'], np.array([1, 2]))\nresults['status'] = 'success'",
        "np.savez(ctx['path'], values=np.array([1, 2]))\nresults['status'] = 'success'",
        "np.savetxt(ctx['path'], np.array([1, 2]))\nresults['status'] = 'success'",
        "np.array([1, 2]).tofile(ctx['path'])\nresults['status'] = 'success'",
        "np.array([1, 2]).dump(ctx['path'])\nresults['status'] = 'success'",
        "import operator\noperator.methodcaller('tofile', ctx['path'])(np.array([1, 2]))\nresults['status'] = 'success'",
    ],
)
async def test_numpy_writes_cannot_leave_the_tool_boundary(tmp_path, source):
    result = await CodeStage._execute_code(
        instance(), source, {"path": str(tmp_path / "owned-output")}, False
    )
    assert not result["success"]
    assert "forbidden" in result["error"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "expression",
    [
        "np.array([1]).ctypes",
        "np.random.PCG64(0).ctypes",
        "np.random.PCG64(0).cffi",
        "np.random.PCG64(0).capsule",
        "np.lib.npyio.NpzFile",
        "np.lib.npyio.DataSource",
        "np.lib.stride_tricks.as_strided",
        "np.rec.fromfile",
        "np.testing",
        "re.enum",
    ],
)
async def test_public_native_and_unlisted_module_capabilities_are_blocked(expression):
    result = await CodeStage._execute_code(
        instance(),
        f"capability = {expression}\nresults['status'] = 'success'",
        {},
        True,
    )
    assert not result["success"]
    assert "forbidden" in result["error"] or "not allowed" in result["error"]


async def test_warm_program_rechecks_dynamic_numpy_operation(tmp_path):
    source = "method = getattr(np, ctx['method'])\nresults['value'] = method(*ctx['args'], **ctx['kwargs'])\nresults['status'] = 'success'"
    router = instance()
    good = await CodeStage._execute_code(
        router, source, {"method": "sum", "args": [[1, 2, 3]], "kwargs": {}}, True
    )
    bad = await CodeStage._execute_code(
        router,
        source,
        {
            "method": "load",
            "args": [str(tmp_path / "not-opened")],
            "kwargs": {"allow_pickle": True},
        },
        True,
    )
    assert good["success"] and good["results"]["value"] == 6
    assert not bad["success"] and "forbidden" in bad["error"]


async def test_numpy_runtime_policy_tightening_applies_to_cached_program(monkeypatch):
    source = "results['value'] = int(np.sum([1,2,3]))\nresults['status'] = 'success'"
    router = instance()
    assert (await CodeStage._execute_code(router, source, {}, True))["success"]
    monkeypatch.setattr(
        CodeGenRouter, "NUMPY_IO_NAMES", CodeGenRouter.NUMPY_IO_NAMES | {"sum"}
    )
    result = await CodeStage._execute_code(router, source, {}, True)
    assert not result["success"] and "forbidden" in result["error"]


async def test_legitimate_numeric_namespaces_and_json_remain_usable():
    source = "import numpy as np\nimport json\narray = np.array([1,2,3])\nresults['mean'] = float(np.mean(array))\nresults['eigenvalues'] = np.linalg.eigvalsh(np.eye(2)).tolist()\nresults['fft'] = np.fft.fft([1,0]).real.tolist()\nresults['random'] = np.random.default_rng(42).integers(0,10,2).tolist()\nresults['json'] = json.loads(json.dumps({'value':3}))\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(instance(), source, {}, True)
    assert result["success"], result
    assert result["results"]["mean"] == 2
    assert result["results"]["eigenvalues"] == [1, 1]
    assert result["results"]["fft"] == [1, 1]
    assert result["results"]["random"] == [0, 7]
    assert result["results"]["json"] == {"value": 3}


@pytest.mark.parametrize(
    "source",
    [
        "np.sum = print\nresults['status'] = 'success'",
        "json.decoder = math\nresults['status'] = 'success'",
        "modules['Tool'].counter = 99\nresults['status'] = 'success'",
        "array = np.array([1,2])\narray.shape = (2,1)\nresults['status'] = 'success'",
    ],
)
async def test_attribute_writes_cannot_mutate_host_namespaces(source):
    result = await CodeStage._execute_code(instance(), source, {}, False)
    assert not result["success"]
    assert "Modifying object attributes" in result["error"]


async def test_in_place_validator_code_patch_invalidates_shared_verdict(monkeypatch):
    source = "results['value'] = 424242\nresults['status'] = 'success'"
    router = instance()
    assert (await CodeStage._execute_code(router, source, {}, True))["success"]

    def reject(router, code):
        return False, "hotpatched policy rejects"

    monkeypatch.setattr(CodeStage._validate_code_safety, "__code__", reject.__code__)
    result = await CodeStage._execute_code(router, source, {}, True)
    assert not result["success"] and result["error"] == "hotpatched policy rejects"


async def test_native_interface_names_do_not_block_unrelated_trusted_tools():
    from types import SimpleNamespace

    async def capsule():
        return 7

    router = instance()
    capsule._tool_info = {"readonly": True}
    router._modules = {"Tool": SimpleNamespace(capsule=capsule)}
    result = await CodeStage._execute_code(
        router,
        "results['value'] = await modules['Tool'].capsule()\nresults['status'] = 'success'",
        {},
        True,
    )
    assert result["success"] and result["results"]["value"] == 7
