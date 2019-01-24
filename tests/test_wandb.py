import argparse
import pytest
import os
import sys
import os
import textwrap
import yaml
import mock
import glob
import socket
import six
import time
import json
from click.testing import CliRunner
from .api_mocks import *

import wandb
from wandb import wandb_run


def test_log(wandb_init_run):
    history_row = {'stuff': 5}
    wandb.log(history_row)
    assert len(wandb.run.history.rows) == 1
    assert set(history_row.items()) <= set(wandb.run.history.rows[0].items())


def test_log_step(wandb_init_run):
    history_row = {'stuff': 5}
    wandb.log(history_row, step=5)
    wandb.log()
    assert len(wandb.run.history.rows) == 1
    assert wandb.run.history.rows[0]['_step'] == 5


def test_nice_log_error():
    with pytest.raises(ValueError):
        wandb.log({"no": "init"})


@pytest.mark.args(sagemaker=True)
def test_sagemaker(wandb_init_run):
    assert wandb.config.fuckin == "A"
    assert wandb.run.id == "sage-maker"
    assert os.getenv('WANDB_TEST_SECRET') == "TRUE"
    assert wandb.run.group == "sage"


@pytest.mark.args(tf_config={"cluster": {"master": ["trainer-4dsl7-master-0:2222"]}, "task": {"type": "master", "index": 0}, "environment": "cloud"})
def test_simple_tfjob(wandb_init_run):
    assert wandb.run.group is None
    assert wandb.run.job_type == "master"


@pytest.mark.args(tf_config={"cluster": {"master": ["trainer-sj2hp-master-0:2222"], "ps": ["trainer-sj2hp-ps-0:2222"], "worker": ["trainer-sj2hp-worker-0:2222"]}, "task": {"type": "worker", "index": 0}, "environment": "cloud"})
def test_distributed_tfjob(wandb_init_run):
    assert wandb.run.group == "trainer-sj2hp"
    assert wandb.run.job_type == "worker"


@pytest.mark.args(tf_config={"cluster": {"corrupt": ["bad"]}})
def test_corrupt_tfjob(wandb_init_run):
    assert wandb.run.group is None


@pytest.mark.args(env={"TF_CONFIG": "garbage"})
def test_bad_json_tfjob(wandb_init_run):
    assert wandb.run.group is None


@pytest.mark.args(error="io")
def test_io_error(wandb_init_run):
    assert isinstance(wandb_init_run, wandb.LaunchError)


@pytest.mark.skip("Need to figure out the headless fun")
@pytest.mark.args(error="socket")
def test_io_error(wandb_init_run):
    assert isinstance(wandb_init_run, wandb.LaunchError)


@pytest.mark.args(dir="/tmp")
def test_custom_dir(wandb_init_run):
    assert len(glob.glob("/tmp/wandb/run-*")) > 0


@pytest.mark.mock_socket
def test_save_policy_symlink(wandb_init_run):
    with open("test.rad", "w") as f:
        f.write("something")
    wandb.save("test.rad")
    assert wandb_init_run.socket.send.called


@pytest.mark.mock_socket
def test_save_absolute_path(wandb_init_run):
    with open("/tmp/test.txt", "w") as f:
        f.write("something")
    wandb.save("/tmp/test.txt")
    assert os.path.exists(os.path.join(wandb_init_run.dir, "test.txt"))


@pytest.mark.mock_socket
def test_save_relative_path(wandb_init_run):
    with open("/tmp/test.txt", "w") as f:
        f.write("something")
    wandb.save("/tmp/test.txt", base_path="/")
    assert os.path.exists(os.path.join(wandb_init_run.dir, "tmp/test.txt"))


@pytest.mark.mock_socket
def test_save_invalid_path(wandb_init_run):
    with open("/tmp/test.txt", "w") as f:
        f.write("something")
    with pytest.raises(ValueError):
        wandb.save("../tmp/../../*.txt", base_path="/tmp")


@pytest.mark.args(resume=True)
def test_auto_resume_first(wandb_init_run):
    assert json.load(open(os.path.join(wandb.wandb_dir(), wandb_run.RESUME_FNAME)))[
        "run_id"] == wandb_init_run.id
    assert not wandb_init_run.resumed


@pytest.mark.args(resume="testy")
def test_auto_resume_manual(wandb_init_run):
    assert wandb_init_run.id == "testy"


@pytest.mark.resume()
@pytest.mark.args(resume=True)
def test_auto_resume_second(wandb_init_run):
    assert wandb_init_run.id == "test"
    assert wandb_init_run.resumed
    assert wandb_init_run.step == 16


@pytest.mark.resume()
@pytest.mark.args(resume=False)
def test_auto_resume_remove(wandb_init_run):
    assert not os.path.exists(os.path.join(
        wandb.wandb_dir(), wandb_run.RESUME_FNAME))


@pytest.mark.jupyter
def test_save_policy_jupyter(wandb_init_run, query_upload_h5, request_mocker):
    with open("test.rad", "w") as f:
        f.write("something")
    #mock = query_upload_h5(request_mocker)
    wandb.run.socket = None
    wandb.save("test.rad")
    assert wandb_init_run._jupyter_agent.rm._user_file_policies == {
        'end': [], 'live': ['test.rad']}


def test_restore(wandb_init_run, request_mocker, download_url, query_run_v2, query_run_files):
    query_run_v2(request_mocker)
    query_run_files(request_mocker)
    download_url(request_mocker, size=10000)
    res = wandb.restore("weights.h5")
    assert os.path.getsize(res.name) == 10000


@pytest.mark.jupyter
def test_jupyter_init(wandb_init_run):
    assert os.getenv("WANDB_JUPYTER")
    wandb.log({"stat": 1})
    fsapi = wandb_init_run.run_manager._api._file_stream_api
    wandb_init_run._stop_jupyter_agent()
    payloads = {c[1][0]: json.loads(c[1][1])
                for c in fsapi.push.mock_calls}
    assert payloads["wandb-history.jsonl"]["stat"] == 1
    assert payloads["wandb-history.jsonl"]["_step"] == 16

    # TODO: saw some global state issues here...
    # assert "" == err


@pytest.mark.jupyter
def test_jupyter_log_history(wandb_init_run, capsys):
    # This simulates what the happens in a Jupyter notebook, it's gnarly
    # because it resumes so this depends on the run_resume_status which returns
    # a run that's at step 15 so calling log will update step to 16
    wandb.log({"something": "new"})
    rm = wandb_init_run.run_manager
    fsapi = rm._api._file_stream_api
    wandb_init_run._stop_jupyter_agent()
    files = [c[1][0] for c in fsapi.push.mock_calls]
    assert sorted(files) == ['wandb-events.jsonl',
                             'wandb-history.jsonl', 'wandb-summary.json']
    wandb.log({"resumed": "log"})
    new_fsapi = wandb_init_run._jupyter_agent.rm._api._file_stream_api
    wandb_init_run.run_manager.test_shutdown()
    payloads = {c[1][0]: json.loads(c[1][1])
                for c in new_fsapi.push.mock_calls}
    assert payloads["wandb-history.jsonl"]["_step"] == 16
    assert payloads["wandb-history.jsonl"]["resumed"] == "log"


@pytest.mark.args(tensorboard=True)
@pytest.mark.skipif(sys.version_info < (3, 6) or os.environ.get("NO_ML") == "true", reason="no tensorboardX in py2 or no ml tests")
def test_tensorboard(wandb_init_run):
    from tensorboardX import SummaryWriter
    writer = SummaryWriter()
    writer.add_scalar('foo', 1, 0)
    writer.close()
    print("Real run: %s", wandb.run)
    print(wandb.run.history.row)
    print(wandb.run.history.rows)
    assert wandb.run.history.row['global_step'] == 0
    assert wandb.run.history.row['foo'] == 1.0


@pytest.mark.unconfigured
def test_not_logged_in(wandb_init_run, capsys):
    out, err = capsys.readouterr()
    assert "wandb isn't configured" in err
    assert "_init_headless called with cloud=False" in out


@pytest.mark.jupyter
@pytest.mark.unconfigured
def test_jupyter_manual_configure(wandb_init_run, capsys):
    out, err = capsys.readouterr()
    assert "Not authenticated" in err
    assert "to display live results" in out
