from ape import reverts
from pytest import fixture

UNIT = 10**18
PERIOD_LENGTH = 6 * 14 * 24 * 60 * 60
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

@fixture
def token(project, deployer):
    return project.MockToken.deploy(sender=deployer)

@fixture
def accountant(project, deployer):
    accountant = project.TeamAccountant.deploy(sender=deployer)
    accountant.set_operator(deployer, True, sender=deployer)
    return accountant

@fixture
def chainlink(project, deployer):
    return project.MockChainlink.deploy(sender=deployer)

@fixture
def oracle(project, deployer, genesis, chainlink):
    oracle = project.BonusPriceOracle.deploy(genesis, sender=deployer)
    oracle.set_price_oracle(chainlink, 24 * 60 * 60, 10**10, sender=deployer)
    return oracle

@fixture
def distributor(chain, project, deployer, genesis, token, accountant, oracle):
    chain.pending_timestamp = genesis
    distributor = project.BonusDistributor.deploy(genesis, token, sender=deployer)
    distributor.set_accountant(accountant, sender=deployer)
    distributor.set_bonus_price_oracle(oracle, sender=deployer)
    oracle.set_bonus_distributor(distributor, sender=deployer)
    return distributor

def test_finalize_first(chain, deployer, alice, bob, accountant, chainlink, distributor):
    chain.pending_timestamp += PERIOD_LENGTH
    chain.mine()
    assert distributor.period() == 1

    ts = chain.pending_timestamp
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    accountant.adjust_revenue(alice, 0, 4 * UNIT, True, sender=deployer)
    distributor.set_bonus_factor(5000, sender=deployer)
    distributor.set_ybc(bob, 1000, sender=deployer)
    
    assert distributor.pending_period() == 0
    assert distributor.ema_revenue() == 0
    assert distributor.parameters(0) == (0, 0, 0)
    assert distributor.finalize_period(sender=deployer).return_value == (0, 2 * UNIT, UNIT)
    assert distributor.pending_period() == 1
    assert distributor.ema_revenue() == 4 * UNIT
    assert distributor.parameters(0) == (5000, 1000, 2 * UNIT)

    with reverts():
        distributor.finalize_period(sender=deployer)

def test_finalize_zero(chain, deployer, alice, bob, accountant, chainlink, distributor):
    # we should still be able to finalize epochs if there is no EMA smoothing and there hasnt been any revenue
    distributor.set_bonus_factor(5000, sender=deployer)
    distributor.set_ybc(bob, 1000, sender=deployer)

    ts = chain.pending_timestamp + PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)
    distributor.finalize_period(sender=deployer)

    accountant.adjust_revenue(alice, 1, UNIT, True, sender=deployer)
    ts += PERIOD_LENGTH
    chainlink.set_data(1, 2 * 10**8, ts, ts, 0, sender=deployer)
    chain.pending_timestamp = ts
    assert distributor.finalize_period(sender=deployer).return_value[2] == UNIT * 18 // 10

def test_ema_revenue(chain, deployer, alice, accountant, chainlink, distributor):
    distributor.set_smoothing_factor(UNIT // 4, sender=deployer)

    accountant.adjust_revenue(alice, 0, 2 * UNIT, True, sender=deployer)
    accountant.adjust_revenue(alice, 1, 6 * UNIT, True, sender=deployer)
    accountant.adjust_revenue(alice, 2, UNIT, True, sender=deployer)

    ts = chain.pending_timestamp

    ts += PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    assert distributor.ema_revenue() == 0
    assert distributor.finalize_period(sender=deployer).return_value == (0, 2 * UNIT, UNIT)
    assert distributor.ema_revenue() == 2 * UNIT

    ts += PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    # 6*1/4 + 2*3/4 = 3
    assert distributor.finalize_period(sender=deployer).return_value == (1, 2 * UNIT, UNIT * 3 // 2)
    assert distributor.ema_revenue() == 3 * UNIT

    ts += PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    # 1*1/4 + 3*3/4 = 2.5
    assert distributor.finalize_period(sender=deployer).return_value[0] == 2
    assert distributor.ema_revenue() == 25 * UNIT // 10

def test_growth_rate_cap_up(chain, deployer, alice, accountant, chainlink, distributor):
    distributor.set_smoothing_factor(UNIT // 4, sender=deployer)
    distributor.set_growth_rate_cap(1000, sender=deployer)

    accountant.adjust_revenue(alice, 0, 2 * UNIT, True, sender=deployer)
    accountant.adjust_revenue(alice, 1, 6 * UNIT, True, sender=deployer)

    ts = chain.pending_timestamp

    ts += PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    assert distributor.finalize_period(sender=deployer).return_value == (0, 2 * UNIT, UNIT)

    ts += PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    # 6*1/4 + 2*3/4 = 3, which is a 50% increase. but increase is capped to 10%
    assert distributor.finalize_period(sender=deployer).return_value == (1, 2 * UNIT, UNIT * 11 // 10)
    assert distributor.parameters(1).bonus_price == 2 * UNIT * 9 // 10

def test_growth_rate_cap_down(chain, deployer, alice, accountant, chainlink, distributor):
    distributor.set_smoothing_factor(UNIT * 4 // 5, sender=deployer)
    distributor.set_growth_rate_cap(1000, sender=deployer)

    accountant.adjust_revenue(alice, 0, 10 * UNIT, True, sender=deployer)
    accountant.adjust_revenue(alice, 1, 5 * UNIT, True, sender=deployer)

    ts = chain.pending_timestamp

    ts += PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    assert distributor.finalize_period(sender=deployer).return_value == (0, 2 * UNIT, UNIT)

    ts += PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    # 5*4/5 + 10*1/5 = 6, which is a 40% decrease. but decrease is capped to 10%
    assert distributor.finalize_period(sender=deployer).return_value == (1, 2 * UNIT, UNIT * 9 // 10)
    assert distributor.parameters(1).bonus_price == 2 * UNIT * 11 // 10

def test_claim(chain, project, deployer, alice, bob, charlie, token, accountant, chainlink, distributor):
    impl = project.Team.deploy(sender=deployer)
    registry = project.TeamRegistry.deploy(0, sender=deployer)
    registry.set_implementation(impl, sender=deployer)
    team_a = registry.add_team("A", alice, sender=deployer).return_value[1]
    team_b = registry.add_team("B", bob, sender=deployer).return_value[1]

    distributor.set_bonus_factor(5000, sender=deployer)
    accountant.adjust_revenue(team_a, 0, 20 * UNIT, True, sender=deployer)
    accountant.adjust_cost(team_a, 0, 8 * UNIT, True, sender=deployer)
    accountant.adjust_revenue(team_b, 0, 4 * UNIT, True, sender=deployer)
    accountant.adjust_cost(team_b, 0, 5 * UNIT, True, sender=deployer)

    ts = chain.pending_timestamp + PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    assert distributor.finalize_period(sender=deployer).return_value == (0, 2 * UNIT, UNIT)
    token.mint(distributor, 10 * UNIT, sender=deployer)

    # bob cant claim from team alice
    with reverts():
        distributor.claim(team_a, sender=bob)
    
    # team alice has a profit of 12
    # bonus factor of 50% and token price of 2 means she will receive 3 tokens
    assert distributor.pending_claims(team_a) == 0
    assert token.balanceOf(charlie) == 0
    assert distributor.claim(team_a, charlie, sender=alice).return_value == (3 * UNIT, 0)
    assert distributor.pending_claims(team_a) == 1
    assert token.balanceOf(charlie) == 3 * UNIT

    # claiming again doesnt do anything
    assert distributor.claim(team_a, charlie, sender=alice).return_value == (0, 0)

    # team bob has no profit
    assert distributor.claim(team_b, sender=bob).return_value == (0, 0)

    # next period the revenue grows by 25%, giving a 25% discount
    ts += PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 4 * 10**8, ts, ts, 0, sender=deployer)

    # profit of 30, factor of 50% and adjusted token price of 4*0.75=3, so will receive 5 tokens
    accountant.adjust_revenue(team_a, 1, 30 * UNIT, True, sender=deployer)
    assert distributor.finalize_period(sender=deployer).return_value == (1, 4 * UNIT, UNIT * 5 // 4)
    assert distributor.claim(team_a, sender=alice).return_value == (5 * UNIT, 0)
    assert token.balanceOf(alice) == 5 * UNIT

def test_claim_ybc(chain, project, deployer, alice, bob, token, accountant, chainlink, distributor):
    impl = project.Team.deploy(sender=deployer)
    registry = project.TeamRegistry.deploy(0, sender=deployer)
    registry.set_implementation(impl, sender=deployer)
    team = registry.add_team("A", alice, sender=deployer).return_value[1]

    vault = project.MockVault.deploy(token, sender=deployer)
    ybc = project.YBCBonusRecipient.deploy(vault, bob, sender=deployer)
    distributor.set_ybc(ybc, 2500, sender=deployer)
    token.mint(distributor, 10 * UNIT, sender=deployer)
    accountant.adjust_revenue(team, 0, 8 * UNIT, True, sender=deployer)

    ts = chain.pending_timestamp + PERIOD_LENGTH
    chain.pending_timestamp = ts
    chainlink.set_data(0, 2 * 10**8, ts, ts, 0, sender=deployer)

    assert distributor.finalize_period(sender=deployer).return_value == (0, 2 * UNIT, UNIT)
    assert distributor.claim(team, sender=alice).return_value == (3 * UNIT, UNIT)
    assert token.balanceOf(alice) == 3 * UNIT
    assert vault.balanceOf(bob) == UNIT

def test_sweep(project, deployer, distributor):
    # tokens can be transfered out
    token = project.MockToken.deploy(sender=deployer)
    token.mint(distributor, 3 * UNIT, sender=deployer)
    assert token.balanceOf(deployer) == 0
    assert token.balanceOf(distributor) == 3 * UNIT
    distributor.sweep(token, UNIT, sender=deployer)
    assert token.balanceOf(deployer) == UNIT
    assert token.balanceOf(distributor) == 2 * UNIT
    distributor.sweep(token, sender=deployer)
    assert token.balanceOf(deployer) == 3 * UNIT
    assert token.balanceOf(distributor) == 0

def test_sweep_permission(project, deployer, alice, distributor):
    # only management can transfer tokens out
    token = project.MockToken.deploy(sender=deployer)
    token.mint(distributor, UNIT, sender=deployer)
    with reverts():
        distributor.sweep(token, sender=alice)
    distributor.sweep(token, sender=deployer)
