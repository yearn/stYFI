from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
RAMP_LENGTH = 4 * EPOCH_LENGTH
COMPONENTS_SENTINEL = "0x1111111111111111111111111111111111111111"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
UNIT = 10**18
SCALES = [1, 4, 1]

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
def ybc_hooks(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def ybc(project, deployer):
    return project.YBC.deploy(sender=deployer)

@fixture
def ybc_aggregator(project, deployer, styfi, genesis, srd, ll_depositors, llrd, styfi_middleware, ll_middlewares, aggregator, ybc_hooks, ybc):
    styfi.set_hooks(styfi_middleware, sender=deployer)
    srd.set_depositor(styfi_middleware, sender=deployer)

    for i in range(len(SCALES)):
        ll_depositors[i].set_hooks(ll_middlewares[i], sender=deployer)
        llrd.set_depositor(ll_depositors[i], ll_middlewares[i], sender=deployer)

    ybc_aggregator = project.YBCWeightAggregator.deploy(genesis, sender=deployer)
    ybc_aggregator.set_weight_aggregator(aggregator, sender=deployer)
    ybc_aggregator.set_upstream_weights(aggregator, sender=deployer)
    ybc_aggregator.set_downstream(ybc_hooks, sender=deployer)

    aggregator.activate([styfi_middleware] + ll_middlewares, sender=deployer)
    aggregator.set_downstream(ybc_aggregator, sender=deployer)

    ybc.set_hooks(ybc_aggregator, sender=deployer)

    return ybc_aggregator

def test_add_member(chain, deployer, alice, bob, charlie, yfi, styfi, genesis, aggregator, ybc_aggregator, ybc_hooks, ybc):
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(styfi, 3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, sender=alice)
    styfi.deposit(UNIT, bob, sender=alice)
    ybc.set_operator(charlie, True, sender=deployer)

    ts = genesis + 9 * EPOCH_LENGTH
    chain.pending_timestamp = ts
    ybc_aggregator.set_upstream_members(ybc, sender=deployer)
    
    # add alice to the YBC, their YBC weight will start ramping from 0
    assert aggregator.weight(alice) == 2 * UNIT
    assert ybc_hooks.last_stake() == (ZERO_ADDRESS, ZERO_ADDRESS, 0, 0, 0)
    assert ybc_aggregator.supply() == 0
    assert ybc_aggregator.total_weight() == 0
    assert ybc_aggregator.staked(alice) == 0
    assert ybc_aggregator.weight(alice) == 0
    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=charlie)
    assert ybc_hooks.last_stake() == (alice, alice, 0, 0, 2 * UNIT)
    assert ybc_aggregator.supply() == 2 * UNIT
    assert ybc_aggregator.total_weight() == 0
    assert ybc_aggregator.staked(alice) == 2 * UNIT
    assert ybc_aggregator.weight(alice) == 0

    ts += EPOCH_LENGTH
    chain.pending_timestamp = ts
    chain.mine()
    assert ybc_aggregator.total_weight() == 2 * UNIT
    assert ybc_aggregator.weight(alice) == UNIT

    # add bob to the YBC too
    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=charlie)
    assert ybc_hooks.last_stake() == (bob, bob, 2 * UNIT, 0, UNIT)
    assert ybc_aggregator.supply() == 3 * UNIT
    assert ybc_aggregator.total_weight() == 2 * UNIT
    assert ybc_aggregator.staked(bob) == UNIT
    assert ybc_aggregator.weight(bob) == 0

    ts += EPOCH_LENGTH
    chain.pending_timestamp = ts
    chain.mine()
    assert ybc_aggregator.supply() == 3 * UNIT
    assert ybc_aggregator.total_weight() == 3 * UNIT
    assert ybc_aggregator.weight(alice) == 2 * UNIT
    assert ybc_aggregator.weight(bob) == UNIT // 2

def test_remove_member(chain, deployer, alice, bob, charlie, yfi, styfi, genesis, ybc_aggregator, ybc_hooks, ybc):
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(styfi, 3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, sender=alice)
    styfi.deposit(UNIT, bob, sender=alice)
    ybc.set_operator(charlie, True, sender=deployer)

    ts = genesis + 9 * EPOCH_LENGTH
    chain.pending_timestamp = ts
    ybc_aggregator.set_upstream_members(ybc, sender=deployer)

    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=charlie)
    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=charlie)

    ts += EPOCH_LENGTH
    chain.pending_timestamp = ts
    chain.mine()
    assert ybc_hooks.last_unstake() == (ZERO_ADDRESS, 0, 0, 0)
    assert ybc_aggregator.supply() == 3 * UNIT
    assert ybc_aggregator.total_weight() == 3 * UNIT
    assert ybc_aggregator.staked(alice) == 2 * UNIT
    assert ybc_aggregator.weight(alice) == UNIT
    ybc.call(ybc, ybc.remove_member.encode_input(alice), sender=charlie)
    assert ybc_hooks.last_unstake() == (alice, 3 * UNIT, 2 * UNIT, 2 * UNIT)
    assert ybc_aggregator.supply() == UNIT
    assert ybc_aggregator.total_weight() == 3 * UNIT
    assert ybc_aggregator.staked(alice) == 0
    assert ybc_aggregator.weight(alice) == 0

    ts += EPOCH_LENGTH
    chain.pending_timestamp = ts
    chain.mine()
    assert ybc_aggregator.total_weight() == UNIT

def test_stake(chain, deployer, alice, bob, charlie, yfi, styfi, genesis, ybc_aggregator, ybc_hooks, ybc):
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(styfi, 3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, sender=alice)
    styfi.deposit(UNIT, bob, sender=alice)
    ybc.set_operator(deployer, True, sender=deployer)

    ts = genesis + 9 * EPOCH_LENGTH
    chain.pending_timestamp = ts
    ybc_aggregator.set_upstream_members(ybc, sender=deployer)

    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)
    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    ts += EPOCH_LENGTH

    # staking (on behalf) of a YBC member
    yfi.mint(charlie, 2 * UNIT, sender=deployer)
    yfi.approve(styfi, 2 * UNIT, sender=charlie)

    chain.pending_timestamp = ts
    chain.mine()
    assert ybc_aggregator.supply() == 3 * UNIT
    assert ybc_aggregator.total_weight() == 3 * UNIT
    assert ybc_aggregator.staked(alice) == 2 * UNIT
    assert ybc_aggregator.weight(alice) == UNIT
    chain.pending_timestamp = ts
    styfi.deposit(UNIT, alice, sender=charlie)
    assert ybc_hooks.last_stake() == (charlie, alice, 3 * UNIT, 2 * UNIT, UNIT)
    assert ybc_aggregator.supply() == 4 * UNIT
    assert ybc_aggregator.total_weight() == 3 * UNIT
    assert ybc_aggregator.staked(alice) == 3 * UNIT
    assert ybc_aggregator.weight(alice) == UNIT

    ts += EPOCH_LENGTH
    chain.pending_timestamp = ts
    chain.mine()
    assert ybc_aggregator.total_weight() == 4 * UNIT
    assert ybc_aggregator.weight(alice) == 2 * UNIT

    # staking of a non-YBC member is ignored
    styfi.deposit(UNIT, sender=charlie)
    assert ybc_aggregator.supply() == 4 * UNIT
    assert ybc_aggregator.staked(charlie) == 0

def test_unstake(chain, deployer, alice, bob, charlie, yfi, styfi, genesis, ybc_aggregator, ybc_hooks, ybc):
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(styfi, 3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, sender=alice)
    styfi.deposit(UNIT, bob, sender=alice)
    ybc.set_operator(deployer, True, sender=deployer)

    ts = genesis + 9 * EPOCH_LENGTH
    chain.pending_timestamp = ts
    ybc_aggregator.set_upstream_members(ybc, sender=deployer)

    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)
    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    ts += EPOCH_LENGTH
    chain.pending_timestamp = ts
    chain.mine()

    # unstaking by a YBC member
    assert ybc_aggregator.supply() == 3 * UNIT
    assert ybc_aggregator.total_weight() == 3 * UNIT
    assert ybc_aggregator.staked(alice) == 2 * UNIT
    assert ybc_aggregator.weight(alice) == UNIT
    chain.pending_timestamp = ts
    styfi.unstake(UNIT, sender=alice)
    assert ybc_hooks.last_unstake() == (alice, 3 * UNIT, 2 * UNIT, UNIT)
    assert ybc_aggregator.supply() == 2 * UNIT
    assert ybc_aggregator.total_weight() == 3 * UNIT
    assert ybc_aggregator.staked(alice) == UNIT
    assert ybc_aggregator.weight(alice) == UNIT // 2

    ts += EPOCH_LENGTH
    chain.pending_timestamp = ts
    chain.mine()
    assert ybc_aggregator.total_weight() == 2 * UNIT
    assert ybc_aggregator.weight(alice) == UNIT

    # unstaking of a non-YBC member is ignored
    yfi.mint(charlie, UNIT, sender=deployer)
    yfi.approve(styfi, UNIT, sender=charlie)
    styfi.deposit(UNIT, sender=charlie)
    styfi.unstake(UNIT, sender=charlie)
    assert ybc_aggregator.supply() == 2 * UNIT
    assert ybc_aggregator.staked(charlie) == 0

def test_transfer(chain, deployer, alice, bob, charlie, yfi, styfi, genesis, ybc_aggregator, ybc_hooks, ybc):
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(styfi, 3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, sender=alice)
    styfi.deposit(UNIT, bob, sender=alice)
    ybc.set_operator(deployer, True, sender=deployer)

    ts = genesis + 9 * EPOCH_LENGTH
    chain.pending_timestamp = ts
    ybc_aggregator.set_upstream_members(ybc, sender=deployer)

    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)
    chain.pending_timestamp = ts
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    ts += EPOCH_LENGTH

    # YBC -> non-YBC is treated as unstaking
    with chain.isolate():
        chain.pending_timestamp = ts
        chain.mine()
        assert ybc_hooks.last_unstake() == (ZERO_ADDRESS, 0, 0, 0)
        assert ybc_aggregator.supply() == 3 * UNIT
        assert ybc_aggregator.total_weight() == 3 * UNIT
        assert ybc_aggregator.staked(alice) == 2 * UNIT
        assert ybc_aggregator.weight(alice) == UNIT
        chain.pending_timestamp = ts
        styfi.transfer(charlie, UNIT, sender=alice)
        assert ybc_hooks.last_unstake() == (alice, 3 * UNIT, 2 * UNIT, UNIT)
        assert ybc_aggregator.supply() == 2 * UNIT
        assert ybc_aggregator.total_weight() == 3 * UNIT
        assert ybc_aggregator.staked(alice) == UNIT
        assert ybc_aggregator.weight(alice) == UNIT // 2

        chain.pending_timestamp = ts + EPOCH_LENGTH
        chain.mine()
        assert ybc_aggregator.total_weight() == 2 * UNIT

    # YBC -> YBC is treated as transfer
    with chain.isolate():
        chain.pending_timestamp = ts
        ybc.call(ybc, ybc.add_member.encode_input(charlie), sender=deployer)

        assert ybc_hooks.last_transfer() == (ZERO_ADDRESS, ZERO_ADDRESS, ZERO_ADDRESS, 0, 0, 0, 0)
        assert ybc_aggregator.supply() == 3 * UNIT
        assert ybc_aggregator.total_weight() == 3 * UNIT
        assert ybc_aggregator.staked(alice) == 2 * UNIT
        assert ybc_aggregator.weight(alice) == UNIT
        assert ybc_aggregator.staked(charlie) == 0
        assert ybc_aggregator.weight(charlie) == 0
        chain.pending_timestamp = ts
        styfi.transfer(charlie, UNIT, sender=alice)
        assert ybc_hooks.last_transfer() == (alice, alice, charlie, 3 * UNIT, 2 * UNIT, 0, UNIT)
        assert ybc_aggregator.supply() == 3 * UNIT
        assert ybc_aggregator.total_weight() == 3 * UNIT
        assert ybc_aggregator.staked(alice) == UNIT
        assert ybc_aggregator.weight(alice) == UNIT // 2
        assert ybc_aggregator.staked(charlie) == UNIT
        assert ybc_aggregator.weight(charlie) == 0

        chain.pending_timestamp = ts + EPOCH_LENGTH
        chain.mine()
        assert ybc_aggregator.weight(alice) == UNIT
        assert ybc_aggregator.weight(charlie) == UNIT // 2

    # non-YBC -> YBC is treated as staking
    with chain.isolate():
        yfi.mint(charlie, UNIT, sender=deployer)
        yfi.approve(styfi, UNIT, sender=charlie)
        styfi.deposit(UNIT, sender=charlie)

        chain.pending_timestamp = ts
        chain.mine()
        assert ybc_aggregator.supply() == 3 * UNIT
        assert ybc_aggregator.total_weight() == 3 * UNIT
        assert ybc_aggregator.staked(alice) == 2 * UNIT
        assert ybc_aggregator.weight(alice) == UNIT
        chain.pending_timestamp = ts
        styfi.transfer(alice, UNIT, sender=charlie)
        assert ybc_hooks.last_stake() == (charlie, alice, 3 * UNIT, 2 * UNIT, UNIT)
        assert ybc_aggregator.supply() == 4 * UNIT
        assert ybc_aggregator.total_weight() == 3 * UNIT
        assert ybc_aggregator.staked(alice) == 3 * UNIT
        assert ybc_aggregator.weight(alice) == UNIT 

        chain.pending_timestamp = ts + EPOCH_LENGTH
        chain.mine()
        assert ybc_aggregator.total_weight() == 4 * UNIT
        assert ybc_aggregator.weight(alice) == 2 * UNIT

    # non-YBC -> non-YBC is ignored
    with chain.isolate():
        n = ybc_hooks.num_triggers()

        yfi.mint(charlie, UNIT, sender=deployer)
        yfi.approve(styfi, UNIT, sender=charlie)
        styfi.deposit(UNIT, sender=charlie)

        chain.pending_timestamp = ts
        chain.mine()
        styfi.transfer(deployer, UNIT, sender=charlie)
        assert ybc_hooks.num_triggers() == n
        assert ybc_aggregator.supply() == 3 * UNIT
        assert ybc_aggregator.staked(charlie) == 0
        assert ybc_aggregator.staked(deployer) == 0
