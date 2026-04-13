from ape import reverts
from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18
SCALES = [1, 2, 1]

@fixture
def srd(chain, project, deployer, reward, distributor, genesis):
    chain.pending_timestamp = genesis
    srd = project.StakingRewardDistributor.deploy(distributor, reward, sender=deployer)
    distributor.add_component(srd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)
    return srd

@fixture
def old_aggregator(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture(autouse=True)
def old_styfi_middleware(project, deployer, styfi, srd, old_aggregator):
    middleware = project.StakingMiddleware.deploy(styfi, srd, old_aggregator, sender=deployer)
    styfi.set_hooks(middleware, sender=deployer)
    srd.set_depositor(middleware, sender=deployer)
    srd.set_staking(styfi, sender=deployer)
    return middleware

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
def ybc_aggregator(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def aggregator(chain, project, deployer, genesis, srd, llrd, ybc_aggregator):
    chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
    aggregator = project.WeightAggregator.deploy(genesis, sender=deployer)
    aggregator.set_downstream(ybc_aggregator, sender=deployer)
    return aggregator

@fixture
def styfi_middleware(project, deployer, styfi, srd, aggregator):
    return project.StakingMiddleware.deploy(styfi, srd, aggregator, sender=deployer)

@fixture
def ll_middlewares(project, deployer, ll_depositors, llrd, aggregator):
    return [project.LiquidLockerMiddleware.deploy(depositor, llrd, aggregator, sender=deployer) for depositor in ll_depositors]

def test_activate(deployer, alice, bob, yfi, styfi, srd, lls, ll_depositors, llrd, aggregator, styfi_middleware, ll_middlewares):
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)
    assert styfi.totalSupply() == UNIT

    yfi.mint(bob, 2 * UNIT, sender=deployer)
    yfi.approve(styfi, 2 * UNIT, sender=bob)
    styfi.deposit(2 * UNIT, sender=bob)
    assert styfi.totalSupply() == 3 * UNIT

    lls[0].mint(alice, 3 * UNIT, sender=deployer)
    lls[0].approve(ll_depositors[0], 3 * UNIT, sender=alice)
    ll_depositors[0].deposit(3 * UNIT, sender=alice)
    assert ll_depositors[0].totalSupply() == 3 * UNIT

    lls[1].mint(alice, 8 * UNIT, sender=deployer)
    lls[1].approve(ll_depositors[1], 8 * UNIT, sender=alice)
    ll_depositors[1].deposit(8 * UNIT, sender=alice)
    assert ll_depositors[1].totalSupply() == 4 * UNIT

    lls[2].mint(alice, 5 * UNIT, sender=deployer)
    lls[2].approve(ll_depositors[2], 5 * UNIT, sender=alice)
    ll_depositors[2].deposit(5 * UNIT, sender=alice)
    assert ll_depositors[2].totalSupply() == 5 * UNIT

    # migrate stYFI and llYFI to new middleware
    styfi.set_hooks(styfi_middleware, sender=deployer)
    srd.set_depositor(styfi_middleware, sender=deployer)

    for i in range(len(SCALES)):
        ll_depositors[i].set_hooks(ll_middlewares[i], sender=deployer)
        llrd.set_depositor(ll_depositors[i], ll_middlewares[i], sender=deployer)

    assert aggregator.supply() == 0
    assert aggregator.total_weight() == 0
    aggregator.activate([styfi_middleware] + ll_middlewares, sender=deployer)
    assert aggregator.supply() == 15 * UNIT
    assert aggregator.total_weight() == 15 * UNIT
    assert aggregator.staked(alice) == 13 * UNIT
    assert aggregator.staked(bob) == 2 * UNIT
    # upon activation, all existing stake has max weight
    assert aggregator.weight(alice) == 13 * UNIT
    assert aggregator.weight(bob) == 2 * UNIT

def test_activate_stake(chain, deployer, alice, bob, yfi, styfi, genesis, srd, lls, ll_depositors, llrd, ybc_aggregator, aggregator, styfi_middleware, ll_middlewares):
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)
    assert styfi.totalSupply() == UNIT

    yfi.mint(bob, 2 * UNIT, sender=deployer)
    yfi.approve(styfi, 2 * UNIT, sender=bob)
    styfi.deposit(2 * UNIT, sender=bob)
    assert styfi.totalSupply() == 3 * UNIT

    lls[0].mint(alice, 3 * UNIT, sender=deployer)
    lls[0].approve(ll_depositors[0], 3 * UNIT, sender=alice)
    ll_depositors[0].deposit(3 * UNIT, sender=alice)
    assert ll_depositors[0].totalSupply() == 3 * UNIT

    lls[1].mint(alice, 8 * UNIT, sender=deployer)
    lls[1].approve(ll_depositors[1], 8 * UNIT, sender=alice)
    ll_depositors[1].deposit(8 * UNIT, sender=alice)
    assert ll_depositors[1].totalSupply() == 4 * UNIT

    lls[2].mint(alice, 5 * UNIT, sender=deployer)
    lls[2].approve(ll_depositors[2], 5 * UNIT, sender=alice)
    ll_depositors[2].deposit(5 * UNIT, sender=alice)
    assert ll_depositors[2].totalSupply() == 5 * UNIT

    # migrate stYFI and llYFI to new middleware
    styfi.set_hooks(styfi_middleware, sender=deployer)
    srd.set_depositor(styfi_middleware, sender=deployer)

    for i in range(len(SCALES)):
        ll_depositors[i].set_hooks(ll_middlewares[i], sender=deployer)
        llrd.set_depositor(ll_depositors[i], ll_middlewares[i], sender=deployer)

    aggregator.activate([styfi_middleware] + ll_middlewares, sender=deployer)

    with chain.isolate():
        # stake more stYFI, followed by llYFI
        yfi.mint(alice, 2 * UNIT, sender=deployer)
        yfi.approve(styfi, 2 * UNIT, sender=alice)

        assert aggregator.supply() == 15 * UNIT
        assert aggregator.total_weight() == 15 * UNIT
        assert aggregator.packed_staked(alice) == 0
        assert aggregator.staked(alice) == 13 * UNIT
        assert aggregator.weight(alice) == 13 * UNIT
        ts = genesis + EPOCH_LENGTH * 9 // 2
        chain.pending_timestamp = ts
        styfi.deposit(2 * UNIT, sender=alice)
        assert aggregator.supply() == 17 * UNIT
        assert aggregator.total_weight() == 15 * UNIT
        packed = aggregator.packed_staked(alice)
        assert (packed >> 200) & (2**40 - 1) == ts # time
        assert packed & (2**100 - 1) == 2 * UNIT # ramping
        assert aggregator.staked(alice) == 15 * UNIT
        assert aggregator.weight(alice) == 13 * UNIT
        assert ybc_aggregator.last_stake() == (alice, alice, 15 * UNIT, 13 * UNIT, 2 * UNIT)

        chain.pending_timestamp = genesis + EPOCH_LENGTH * 5
        chain.mine()
        assert aggregator.total_weight() == 17 * UNIT
        assert aggregator.weight(alice) == 13 * UNIT + 2 * UNIT // 8

        chain.pending_timestamp = genesis + EPOCH_LENGTH * 6
        chain.mine()
        assert aggregator.weight(alice) == 13 * UNIT + 2 * UNIT * 3 // 8

        lls[0].mint(alice, 3 * UNIT, sender=deployer)
        lls[0].approve(ll_depositors[0], 3 * UNIT, sender=alice)

        chain.pending_timestamp = ts + 2 * EPOCH_LENGTH
        ll_depositors[0].deposit(3 * UNIT, sender=alice)
        assert ybc_aggregator.last_stake() == (alice, alice, 17 * UNIT, 15 * UNIT, 3 * UNIT)

        chain.pending_timestamp = genesis + EPOCH_LENGTH * 7
        chain.mine()
        assert aggregator.weight(alice) == 14 * UNIT + UNIT * 4 // 8

    # stake more llYFI
    lls[0].mint(alice, 2 * UNIT, sender=deployer)
    lls[0].approve(ll_depositors[0], 2 * UNIT, sender=alice)

    assert aggregator.supply() == 15 * UNIT
    assert aggregator.total_weight() == 15 * UNIT
    assert aggregator.packed_staked(alice) == 0
    assert aggregator.staked(alice) == 13 * UNIT
    assert aggregator.weight(alice) == 13 * UNIT
    chain.pending_timestamp = genesis + EPOCH_LENGTH * 9 // 2
    ll_depositors[0].deposit(2 * UNIT, sender=alice)
    assert aggregator.supply() == 17 * UNIT
    assert aggregator.total_weight() == 15 * UNIT
    assert aggregator.packed_staked(alice) > 0
    assert aggregator.staked(alice) == 15 * UNIT
    assert aggregator.weight(alice) == 13 * UNIT
    assert ybc_aggregator.last_stake() == (alice, alice, 15 * UNIT, 13 * UNIT, 2 * UNIT)

    chain.pending_timestamp = genesis + EPOCH_LENGTH * 5
    chain.mine()
    assert aggregator.total_weight() == 17 * UNIT
    assert aggregator.weight(alice) == 13 * UNIT + 2 * UNIT // 8

    chain.pending_timestamp = genesis + EPOCH_LENGTH * 6
    chain.mine()
    assert aggregator.weight(alice) == 13 * UNIT + 2 * UNIT * 3 // 8

def test_activate_unstake(chain, deployer, alice, bob, yfi, styfi, genesis, srd, lls, ll_depositors, llrd, ybc_aggregator, aggregator, styfi_middleware, ll_middlewares):
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)
    assert styfi.totalSupply() == UNIT

    yfi.mint(bob, 2 * UNIT, sender=deployer)
    yfi.approve(styfi, 2 * UNIT, sender=bob)
    styfi.deposit(2 * UNIT, sender=bob)
    assert styfi.totalSupply() == 3 * UNIT

    lls[0].mint(alice, 3 * UNIT, sender=deployer)
    lls[0].approve(ll_depositors[0], 3 * UNIT, sender=alice)
    ll_depositors[0].deposit(3 * UNIT, sender=alice)
    assert ll_depositors[0].totalSupply() == 3 * UNIT

    lls[1].mint(alice, 8 * UNIT, sender=deployer)
    lls[1].approve(ll_depositors[1], 8 * UNIT, sender=alice)
    ll_depositors[1].deposit(8 * UNIT, sender=alice)
    assert ll_depositors[1].totalSupply() == 4 * UNIT

    lls[2].mint(alice, 5 * UNIT, sender=deployer)
    lls[2].approve(ll_depositors[2], 5 * UNIT, sender=alice)
    ll_depositors[2].deposit(5 * UNIT, sender=alice)
    assert ll_depositors[2].totalSupply() == 5 * UNIT

    # migrate stYFI and llYFI to new middleware
    styfi.set_hooks(styfi_middleware, sender=deployer)
    srd.set_depositor(styfi_middleware, sender=deployer)

    for i in range(len(SCALES)):
        ll_depositors[i].set_hooks(ll_middlewares[i], sender=deployer)
        llrd.set_depositor(ll_depositors[i], ll_middlewares[i], sender=deployer)

    aggregator.activate([styfi_middleware] + ll_middlewares, sender=deployer)

    with chain.isolate():
        # unstake stYFI
        assert aggregator.supply() == 15 * UNIT
        assert aggregator.total_weight() == 15 * UNIT
        assert aggregator.packed_staked(alice) == 0
        assert aggregator.staked(alice) == 13 * UNIT
        assert aggregator.weight(alice) == 13 * UNIT
        chain.pending_timestamp = genesis + EPOCH_LENGTH * 9 // 2
        styfi.unstake(UNIT, sender=alice)
        assert aggregator.supply() == 14 * UNIT
        assert aggregator.total_weight() == 15 * UNIT
        assert aggregator.staked(alice) == 12 * UNIT
        assert aggregator.weight(alice) == 12 * UNIT
        assert ybc_aggregator.last_unstake() == (alice, 15 * UNIT, 13 * UNIT, UNIT)

    # unstake llYFI
    assert aggregator.supply() == 15 * UNIT
    assert aggregator.total_weight() == 15 * UNIT
    assert aggregator.packed_staked(alice) == 0
    assert aggregator.staked(alice) == 13 * UNIT
    assert aggregator.weight(alice) == 13 * UNIT
    chain.pending_timestamp = genesis + EPOCH_LENGTH * 9 // 2
    ll_depositors[0].unstake(2 * UNIT, sender=alice)
    assert aggregator.supply() == 13 * UNIT
    assert aggregator.total_weight() == 15 * UNIT
    assert aggregator.packed_staked(alice) > 0
    assert aggregator.staked(alice) == 11 * UNIT
    assert aggregator.weight(alice) == 11 * UNIT
    assert ybc_aggregator.last_unstake() == (alice, 15 * UNIT, 13 * UNIT, 2 * UNIT)
