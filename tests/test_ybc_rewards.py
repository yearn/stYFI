from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
RAMP_LENGTH = 4 * EPOCH_LENGTH
COMPONENTS_SENTINEL = "0x1111111111111111111111111111111111111111"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DUST = 10**12
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
def ybc(project, deployer):
    return project.YBC.deploy(sender=deployer)

@fixture
def ybc_aggregator(project, deployer, styfi, genesis, srd, ll_depositors, llrd, styfi_middleware, ll_middlewares, aggregator, ybc):
    styfi.set_hooks(styfi_middleware, sender=deployer)
    srd.set_depositor(styfi_middleware, sender=deployer)

    for i in range(len(SCALES)):
        ll_depositors[i].set_hooks(ll_middlewares[i], sender=deployer)
        llrd.set_depositor(ll_depositors[i], ll_middlewares[i], sender=deployer)

    ybc_aggregator = project.YBCWeightAggregator.deploy(genesis, sender=deployer)
    ybc_aggregator.set_weight_aggregator(aggregator, sender=deployer)
    ybc_aggregator.set_upstream_weights(aggregator, sender=deployer)
    ybc_aggregator.set_upstream_members(ybc, sender=deployer)

    aggregator.activate([styfi_middleware] + ll_middlewares, sender=deployer)
    aggregator.set_downstream(ybc_aggregator, sender=deployer)

    ybc.set_hooks(ybc_aggregator, sender=deployer)
    return ybc_aggregator

@fixture
def claimer(project, deployer, reward, srd, llrd):
    claimer = project.RewardClaimer.deploy(reward, sender=deployer)
    claimer.add_component(srd, sender=deployer)
    claimer.add_component(llrd, sender=deployer)
    srd.set_claimer(claimer, True, sender=deployer)
    llrd.set_claimer(claimer, True, sender=deployer)
    return claimer

@fixture
def ybc_rewards(project, deployer, reward, ybc, ybc_aggregator, claimer):
    rewards = project.YBCRewardDistributor.deploy(ybc, reward, sender=deployer)
    rewards.set_weight_aggregator(ybc_aggregator, sender=deployer)
    rewards.set_upstream_weights(ybc_aggregator, sender=deployer)
    rewards.set_claim_from(claimer, sender=deployer)
    rewards.set_claimer(claimer, True, sender=deployer)

    ybc_aggregator.set_downstream(rewards, sender=deployer)
    ybc.set_operator(rewards, True, sender=deployer)
    claimer.add_component(rewards, sender=deployer)
    return rewards

def test_claim(chain, deployer, alice, bob, charlie, reward, distributor,yfi, styfi, genesis, ybc, claimer, ybc_rewards):
    yfi.mint(deployer, 20 * UNIT, sender=deployer)
    yfi.approve(styfi, 20 * UNIT, sender=deployer)
    styfi.deposit(2 * UNIT, alice, sender=deployer)
    styfi.deposit(3 * UNIT, bob, sender=deployer)
    styfi.deposit(5 * UNIT, charlie, sender=deployer)
    styfi.deposit(10 * UNIT, ybc, sender=deployer)

    ybc.set_operator(deployer, True, sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    amt = 80 * UNIT + 4 * DUST
    reward.mint(deployer, amt, sender=deployer)
    reward.approve(distributor, amt, sender=deployer)
    distributor.deposit(4, amt, sender=deployer)

    ts = genesis + EPOCH_LENGTH * 11 // 2

    assert reward.balanceOf(alice) == 0
    assert ybc_rewards.reward_integral() == 0
    assert ybc_rewards.account_reward_integral(alice) == 0
    chain.pending_timestamp = ts
    assert claimer.claim(sender=alice).return_value == 12 * UNIT # 4 (own) + 8 (ybc)
    assert reward.balanceOf(alice) == 12 * UNIT
    integral = ybc_rewards.reward_integral()
    assert integral == 4 * 10**30
    assert ybc_rewards.account_reward_integral(alice) == integral

    assert ybc_rewards.account_reward_integral(bob) == 0
    chain.pending_timestamp = ts
    assert claimer.claim(sender=bob).return_value == 18 * UNIT # 6 (own) + 12 (ybc)
    assert reward.balanceOf(bob) == 18 * UNIT
    assert ybc_rewards.account_reward_integral(bob) == integral

    chain.pending_timestamp = ts
    assert ybc_rewards.account_reward_integral(charlie) == 0
    assert claimer.claim(sender=charlie).return_value == 10 * UNIT # 10 (own)
    assert reward.balanceOf(charlie) == 10 * UNIT
    assert ybc_rewards.account_reward_integral(charlie) == 0

def test_transfer(chain, deployer, alice, bob, charlie, reward, distributor,yfi, styfi, genesis, ybc, claimer, ybc_rewards):
    yfi.mint(deployer, 20 * UNIT, sender=deployer)
    yfi.approve(styfi, 20 * UNIT, sender=deployer)
    styfi.deposit(2 * UNIT, alice, sender=deployer)
    styfi.deposit(3 * UNIT, bob, sender=deployer)
    styfi.deposit(5 * UNIT, charlie, sender=deployer)
    styfi.deposit(10 * UNIT, ybc, sender=deployer)

    ybc.set_operator(deployer, True, sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    amt = 80 * UNIT + 4 * DUST
    reward.mint(deployer, amt, sender=deployer)
    reward.approve(distributor, amt, sender=deployer)
    distributor.deposit(4, amt, sender=deployer)

    ts = genesis + EPOCH_LENGTH * 11 // 2

    assert ybc_rewards.account_reward_integral(alice) == 0
    assert ybc_rewards.account_reward_integral(bob) == 0
    assert ybc_rewards.pending_rewards(alice) == 0
    assert ybc_rewards.pending_rewards(bob) == 0
    chain.pending_timestamp = ts
    styfi.transfer(bob, UNIT, sender=alice)
    assert ybc_rewards.account_reward_integral(alice) > 0
    assert ybc_rewards.account_reward_integral(bob) > 0
    assert ybc_rewards.pending_rewards(alice) == 8 * UNIT
    assert ybc_rewards.pending_rewards(bob) == 12 * UNIT

def test_stake(chain, deployer, alice, bob, charlie, reward, distributor,yfi, styfi, genesis, ybc, claimer, ybc_rewards):
    yfi.mint(deployer, 21 * UNIT, sender=deployer)
    yfi.approve(styfi, 21 * UNIT, sender=deployer)
    styfi.deposit(2 * UNIT, alice, sender=deployer)
    styfi.deposit(3 * UNIT, bob, sender=deployer)
    styfi.deposit(5 * UNIT, charlie, sender=deployer)
    styfi.deposit(10 * UNIT, ybc, sender=deployer)

    ybc.set_operator(deployer, True, sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    amt = 80 * UNIT + 4 * DUST
    reward.mint(deployer, amt, sender=deployer)
    reward.approve(distributor, amt, sender=deployer)
    distributor.deposit(4, amt, sender=deployer)

    ts = genesis + EPOCH_LENGTH * 11 // 2

    assert ybc_rewards.account_reward_integral(alice) == 0
    assert ybc_rewards.account_reward_integral(bob) == 0
    assert ybc_rewards.pending_rewards(alice) == 0
    assert ybc_rewards.pending_rewards(bob) == 0
    chain.pending_timestamp = ts
    styfi.deposit(UNIT, alice, sender=deployer)
    assert ybc_rewards.account_reward_integral(alice) > 0
    assert ybc_rewards.account_reward_integral(bob) == 0
    assert ybc_rewards.pending_rewards(alice) == 8 * UNIT
    assert ybc_rewards.pending_rewards(bob) == 0

def test_unstake(chain, deployer, alice, bob, charlie, reward, distributor,yfi, styfi, genesis, ybc, claimer, ybc_rewards):
    yfi.mint(deployer, 20 * UNIT, sender=deployer)
    yfi.approve(styfi, 20 * UNIT, sender=deployer)
    styfi.deposit(2 * UNIT, alice, sender=deployer)
    styfi.deposit(3 * UNIT, bob, sender=deployer)
    styfi.deposit(5 * UNIT, charlie, sender=deployer)
    styfi.deposit(10 * UNIT, ybc, sender=deployer)

    ybc.set_operator(deployer, True, sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    amt = 80 * UNIT + 4 * DUST
    reward.mint(deployer, amt, sender=deployer)
    reward.approve(distributor, amt, sender=deployer)
    distributor.deposit(4, amt, sender=deployer)

    ts = genesis + EPOCH_LENGTH * 11 // 2

    assert ybc_rewards.account_reward_integral(alice) == 0
    assert ybc_rewards.account_reward_integral(bob) == 0
    assert ybc_rewards.pending_rewards(alice) == 0
    assert ybc_rewards.pending_rewards(bob) == 0
    chain.pending_timestamp = ts
    styfi.unstake(UNIT, sender=alice)
    assert ybc_rewards.account_reward_integral(alice) > 0
    assert ybc_rewards.account_reward_integral(bob) == 0
    assert ybc_rewards.pending_rewards(alice) == 8 * UNIT
    assert ybc_rewards.pending_rewards(bob) == 0
