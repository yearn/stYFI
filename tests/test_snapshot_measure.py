from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
UNIT = 10**18
SCALES = [1, 2, 3]


@fixture
def hooks(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def styfi(project, deployer, yfi, hooks):
    styfi = project.StakedYFI.deploy(yfi, sender=deployer)
    styfi.set_hooks(hooks, sender=deployer)
    return styfi

@fixture
def styfix(project, deployer, hooks, styfi):
    styfix = project.DelegatedStakedYFI.deploy(styfi, sender=deployer)
    styfix.set_hooks(hooks, sender=deployer)
    return styfix

@fixture
def ll_tokens(project, deployer):
    return [project.MockToken.deploy(sender=deployer) for _ in SCALES]

@fixture
def ll_depositors(project, deployer, hooks, ll_tokens):
    depositors = []
    for scale, ll_token in zip(SCALES, ll_tokens):
        depositor = project.LiquidLockerDepositor.deploy(ll_token, scale, "", "", sender=deployer)
        depositor.set_hooks(hooks, sender=deployer)
        depositor.set_capacity(UNIT, sender=deployer)
        depositors.append(depositor)
    return depositors

@fixture
def veyfi(project, deployer):
    return project.MockVotingEscrow.deploy(sender=deployer)

@fixture
def ve_reward_distributor(project, deployer, reward, veyfi, distributor):
    return project.VotingEscrowRewardDistributor.deploy(distributor, reward, veyfi, sender=deployer)

@fixture
def measure(project, deployer, styfi, styfix, ll_depositors, ve_reward_distributor):
    return project.SnapshotMeasure.deploy(styfi, styfix, ll_depositors, ve_reward_distributor, sender=deployer)

def test_measure(chain, deployer, alice, yfi, genesis, styfi, ll_tokens, ll_depositors, veyfi, ve_reward_distributor, measure):
    chain.pending_timestamp = genesis
    assert measure.balanceOf(alice) == 0

    # stYFI
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)
    assert measure.balanceOf(alice) == UNIT

    # liquid lockers
    for i in range(3):
        amount = SCALES[i] * UNIT
        ll_tokens[i].mint(alice, amount, sender=deployer)
        ll_tokens[i].approve(ll_depositors[i], amount, sender=alice)
        ll_depositors[i].deposit(amount, sender=alice)
        assert measure.balanceOf(alice) == (i + 2) * UNIT

    # veYFI
    # before migrating
    unlock = genesis + 10 * EPOCH_LENGTH
    veyfi.set_locked(alice, UNIT, unlock, sender=deployer)
    ve_reward_distributor.set_snapshot(alice, UNIT, 20, unlock, sender=deployer)
    assert measure.balanceOf(alice) == 4 * UNIT

    # after migrating
    ve_reward_distributor.migrate(sender=alice)
    assert measure.balanceOf(alice) == 5 * UNIT

    # unstake stYFI
    styfi.unstake(UNIT, sender=alice)
    assert measure.balanceOf(alice) == 4 * UNIT

    # unstake liquid lockers
    for i in range(3):
        ll_depositors[i].unstake(UNIT, sender=alice)
        assert measure.balanceOf(alice) == (3 - i) * UNIT
    
    # early exit veYFI
    veyfi.set_locked(alice, 0, 0, sender=deployer)
    assert measure.balanceOf(alice) == 0

def test_ybc(chain, deployer, alice, bob, yfi, styfix, genesis, measure):
    chain.pending_timestamp = genesis
    
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(styfix, UNIT, sender=alice)

    # depositing into stYFIx doesnt give the user a balance
    assert measure.balanceOf(alice) == 0
    styfix.deposit(UNIT, sender=alice)
    assert measure.balanceOf(alice) == 0

    # stYFIx is delegated to the YBC
    assert measure.balanceOf(bob) == 0
    measure.set_ybc(bob, sender=deployer)
    assert measure.balanceOf(bob) == UNIT
