from ape import reverts
from pytest import fixture

UNIT = 10**18

@fixture
def veyfi(project, deployer):
    return project.MockVotingEscrow.deploy(sender=deployer)

@fixture
def snapshot(project, deployer, veyfi):
    return project.VotingEscrowSnapshot.deploy(veyfi, sender=deployer)

def test_set_snapshot(chain, deployer, alice, veyfi, snapshot):
    # snapshot can be set
    ts = chain.pending_timestamp + 100
    veyfi.set_locked(alice, UNIT, ts, sender=deployer)

    assert snapshot.snapshot(alice) == (0, 0, 0)
    snapshot.set_snapshot(alice, UNIT, 4, ts, sender=deployer)
    assert snapshot.snapshot(alice) == (UNIT, 4, ts)
    assert snapshot.locked(alice) == (UNIT, 4, ts)

def test_early_exit(chain, deployer, alice, veyfi, snapshot):
    # early exits are detected
    ts = chain.pending_timestamp + 100
    veyfi.set_locked(alice, UNIT, ts, sender=deployer)

    assert snapshot.snapshot(alice) == (0, 0, 0)
    snapshot.set_snapshot(alice, UNIT, 4, ts, sender=deployer)
    assert snapshot.snapshot(alice) == (UNIT, 4, ts)
    assert snapshot.locked(alice) == (UNIT, 4, ts)

    veyfi.set_locked(alice, 0, 0, sender=deployer)
    assert snapshot.locked(alice) == (0, 0, 0)

    # adding a shorter lock back doesnt count
    veyfi.set_locked(alice, UNIT, ts - 1, sender=deployer)
    assert snapshot.locked(alice) == (0, 0, 0)

    # neither does a lock for a smaller amount
    veyfi.set_locked(alice, UNIT - 1, ts, sender=deployer)
    assert snapshot.locked(alice) == (0, 0, 0)

    veyfi.set_locked(alice, UNIT, ts, sender=deployer)
    assert snapshot.locked(alice) == (UNIT, 4, ts)

# the test below is the only one that requires us to run a fork of mainnet
# however if we uncomment and run as-is we encounter the same issue as https://github.com/ApeWorX/ape/issues/2715
# the test can run succesfully if we change `default_network` in `ape-config` to `mainnet-fork`
# and remove the fork contexts in the test. since this will make all tests slower we opted to not do that

# def test_real_veyfi(networks, project, deployer):
#     tgt = "0xF750162fD81F9a436d74d737EF6eE8FC08e98220"
#     amt = 236 * 10**18
#     ts = 1888185600
#     with networks.ethereum.mainnet.use_provider("node") as node:
#         with networks.fork(provider_name="foundry", block_number=23930000) as fork:
#             print(f'AP: {networks.active_provider}')
#             veyfi = project.MockVotingEscrow.at("0x90c1f9220d90d3966FbeE24045EDd73E1d588aD5")
#             print(veyfi.locked(tgt))
#             snapshot = project.VotingEscrowSnapshot.deploy(veyfi, sender=deployer)
#             snapshot.set_snapshot(tgt, amt, 420, ts, sender=deployer)
#             assert snapshot.locked(tgt) == (amt, 420, ts)
