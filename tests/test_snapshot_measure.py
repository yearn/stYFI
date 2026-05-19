from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
UNIT = 10**18
SCALES = [1, 2, 3]
COMPONENTS_SENTINEL = "0x1111111111111111111111111111111111111111"

@fixture
def srd(chain, project, deployer, reward, styfi, distributor, genesis):
    chain.pending_timestamp = genesis
    srd = project.StakingRewardDistributor.deploy(distributor, reward, sender=deployer)
    srd.set_staking(styfi, sender=deployer)
    distributor.add_component(srd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)
    return srd

@fixture
def lls(project, deployer):
    return [project.MockToken.deploy(sender=deployer) for _ in SCALES]

@fixture
def ll_depositors(project, deployer, lls):
    return [project.LiquidLockerDepositor.deploy(ll, scale, "", "", sender=deployer) for scale, ll in zip(SCALES, lls)]

@fixture
def llrd(project, deployer, reward, distributor, ll_depositors):
    llrd = project.LiquidLockerRewardDistributor.deploy(distributor, reward, 100, ll_depositors, sender=deployer)
    distributor.add_component(llrd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)
    for depositor in ll_depositors:
        depositor.set_capacity(10**20, sender=deployer)
        depositor.set_hooks(llrd, sender=deployer)
    return llrd

@fixture
def aggregator(chain, project, deployer, genesis, srd, llrd):
    chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
    return project.WeightAggregator.deploy(genesis, sender=deployer)

@fixture
def styfi_middleware(project, deployer, styfi, srd, aggregator):
    return project.StakingMiddleware.deploy(styfi, srd, aggregator, sender=deployer)

@fixture
def ll_middlewares(project, deployer, ll_depositors, llrd, aggregator):
    return [project.LiquidLockerMiddleware.deploy(depositor, llrd, aggregator, sender=deployer) for depositor in ll_depositors]

@fixture
def veyfi(project, deployer):
    return project.MockVotingEscrow.deploy(sender=deployer)

@fixture
def ve_reward_distributor(project, deployer, reward, veyfi, distributor):
    return project.VotingEscrowRewardDistributor.deploy(distributor, reward, veyfi, sender=deployer)

@fixture
def hooks(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def styfix(project, deployer, hooks, styfi):
    styfix = project.DelegatedStakedYFI.deploy(styfi, sender=deployer)
    styfix.set_hooks(hooks, sender=deployer)
    return styfix

@fixture
def measure(project, deployer, styfi, srd, ll_depositors, llrd, styfi_middleware, ll_middlewares, aggregator, ve_reward_distributor, styfix):
    styfi.set_hooks(styfi_middleware, sender=deployer)
    srd.set_depositor(styfi_middleware, sender=deployer)

    for i in range(len(SCALES)):
        ll_depositors[i].set_hooks(ll_middlewares[i], sender=deployer)
        llrd.set_depositor(ll_depositors[i], ll_middlewares[i], sender=deployer)

    aggregator.activate([styfi_middleware] + ll_middlewares, sender=deployer)

    return project.SnapshotMeasure.deploy(styfix, aggregator, ve_reward_distributor, sender=deployer)

def test_measure(chain, deployer, alice, yfi, genesis, styfi, lls, ll_depositors, veyfi, ve_reward_distributor, measure):
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
        lls[i].mint(alice, amount, sender=deployer)
        lls[i].approve(ll_depositors[i], amount, sender=alice)
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
