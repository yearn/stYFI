from ape import reverts, Contract
from pytest import fixture

VESTING_FACTORY = "0x200C92Dd85730872Ab6A1e7d5E40A067066257cF"

UNIT = 10**18
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
PERIOD_LENGTH = 6 * 14 * 24 * 60 * 60

@fixture
def registry(chain, project, deployer, genesis):
    chain.pending_timestamp = genesis
    impl = project.Team.deploy(sender=deployer)
    registry = project.TeamRegistry.deploy(genesis, sender=deployer)
    registry.set_implementation(impl, sender=deployer)
    return registry

@fixture
def team(networks, accounts, deployer, alice, registry):
    team = registry.add_team("A", alice, sender=deployer).return_value[1]
    networks.active_provider.set_balance(team, UNIT)
    return accounts[team]

@fixture
def accountant(project, deployer):
    return project.TeamAccountant.deploy(sender=deployer)

@fixture
def distributor(project, deployer, genesis, registry, accountant):
    distributor = project.FundingDistributor.deploy(genesis, sender=deployer)
    distributor.set_registry(registry, sender=deployer)
    distributor.set_accountant(accountant, sender=deployer)
    accountant.set_operator(distributor, True, sender=deployer)
    return distributor

@fixture
def token(project, deployer):
    return project.MockToken.deploy(sender=deployer)

@fixture
def oracle(project, deployer):
    return project.MockOracle.deploy(sender=deployer)

def test_approve(deployer, distributor, token, oracle, team):
    oracle.set_price(token, 2 * UNIT, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)

    assert distributor.num_approvals() == 0
    assert distributor.approvals(0) == (ZERO_ADDRESS, 0, ZERO_ADDRESS, 0, 0, 0)
    distributor.approve(team, 1, token, UNIT, 1000, sender=deployer)
    assert distributor.num_approvals() == 1
    assert distributor.approvals(0) == (team, 1, token, UNIT, 1000, 0)

def test_claim_immediate(deployer, bob, accountant, distributor, token, oracle, team):
    token.mint(distributor, 4 * UNIT, sender=deployer)
    oracle.set_price(token, 2 * UNIT, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)
    distributor.approve(team, 0, token, 4 * UNIT, 0, sender=deployer)

    # claim
    assert distributor.claimable(0) == 4 * UNIT
    assert distributor.costs(team, 0, token) == (0, 0)
    assert accountant.team_costs(team, 0) == 0
    assert accountant.global_costs(0) == 0
    assert token.balanceOf(distributor) == 4 * UNIT
    assert token.balanceOf(bob) == 0
    assert distributor.claim(0, UNIT, bob, sender=team).return_value == (0, 2 * UNIT, ZERO_ADDRESS)
    assert distributor.claimable(0) == 3 * UNIT
    assert distributor.approvals(0) == (team, 0, token, 4 * UNIT, 0, UNIT)
    assert distributor.costs(team, 0, token) == (UNIT, 2 * UNIT)
    assert accountant.team_costs(team, 0) == 2 * UNIT
    assert accountant.global_costs(0) == 2 * UNIT
    assert token.balanceOf(distributor) == 3 * UNIT
    assert token.balanceOf(bob) == UNIT

    # change price, claim again from the same approval
    oracle.set_price(token, 5 * UNIT, sender=deployer)
    assert distributor.claim(0, 2 * UNIT, team, sender=team).return_value == (0, 10 * UNIT, ZERO_ADDRESS)
    assert distributor.claimable(0) == UNIT
    assert distributor.approvals(0) == (team, 0, token, 4 * UNIT, 0, 3 * UNIT)
    assert distributor.costs(team, 0, token) == (3 * UNIT, 4 * UNIT)
    assert accountant.team_costs(team, 0) == 12 * UNIT
    assert accountant.global_costs(0) == 12 * UNIT
    assert token.balanceOf(distributor) == UNIT
    assert token.balanceOf(team) == 2 * UNIT

def test_claim_stream(chain, project, deployer, alice, bob, genesis, registry, accountant, distributor, token, oracle):
    registry.add_team("A", alice, sender=deployer)
    token.mint(distributor, 4 * UNIT, sender=deployer)
    oracle.set_price(token, UNIT, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)
    distributor.set_vesting_factory(VESTING_FACTORY, sender=deployer)
    distributor.approve(alice, 0, token, 4 * UNIT, 1000, sender=deployer)

    ret = distributor.claim(0, 4 * UNIT, bob, sender=alice).return_value
    assert ret[0] == 0 and ret[1] == 4 * UNIT
    assert ret[2] != ZERO_ADDRESS
    assert accountant.team_costs(alice, 0) == 4 * UNIT

    vest = project.MockVest.at(ret[2])
    assert vest.recipient() == bob
    assert vest.token() == token
    assert vest.start_time() == genesis
    assert vest.end_time() == genesis + 1000
    assert vest.cliff_length() == 0
    assert vest.total_locked() == 4 * UNIT

    chain.pending_timestamp = genesis + 250
    assert token.balanceOf(bob) == 0
    vest.claim(sender=bob)
    assert token.balanceOf(bob) == UNIT

def test_claim_permission(deployer, bob, distributor, token, oracle, team):
    token.mint(distributor, UNIT, sender=deployer)
    oracle.set_price(token, UNIT, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)
    distributor.approve(team, 0, token, UNIT, 0, sender=deployer)

    with reverts():
        distributor.claim(0, UNIT, bob, sender=bob)
    distributor.claim(0, UNIT, bob, sender=team)

def test_claim_early(chain, deployer, distributor, token, oracle, team):
    token.mint(distributor, UNIT, sender=deployer)
    oracle.set_price(token, UNIT, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)
    distributor.approve(team, 1, token, UNIT, 0, sender=deployer)

    with reverts():
        distributor.claim(0, UNIT, team, sender=team)

    chain.pending_timestamp += PERIOD_LENGTH
    distributor.claim(0, UNIT, team, sender=team)

def test_claim_late(chain, deployer, distributor, token, oracle, team):
    token.mint(distributor, UNIT, sender=deployer)
    oracle.set_price(token, UNIT, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)
    distributor.approve(team, 0, token, UNIT, 0, sender=deployer)

    chain.pending_timestamp += PERIOD_LENGTH
    with reverts():
        distributor.claim(0, UNIT, team, sender=team)

def test_claim_excessive(deployer, distributor, token, oracle, team):
    token.mint(distributor, 3 * UNIT, sender=deployer)
    oracle.set_price(token, UNIT, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)
    distributor.approve(team, 0, token, 2 * UNIT, 0, sender=deployer)

    with reverts():
        distributor.claim(0, 3 * UNIT, team, sender=team)
    distributor.claim(0, UNIT, team, sender=team)
    with reverts():
        distributor.claim(0, 2 * UNIT, team, sender=team)
    distributor.claim(0, UNIT, team, sender=team)
    with reverts():
        distributor.claim(0, UNIT, team, sender=team)

def test_refund(deployer, accountant, distributor, token, oracle, team):
    token.mint(distributor, 4 * UNIT, sender=deployer)
    oracle.set_price(token, 2 * UNIT, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)
    distributor.approve(team, 0, token, 4 * UNIT, 0, sender=deployer)

    distributor.claim(0, UNIT, team, sender=team)
    oracle.set_price(token, 5 * UNIT, sender=deployer)
    distributor.claim(0, 2 * UNIT, team, sender=team)
    assert distributor.costs(team, 0, token) == (3 * UNIT, 4 * UNIT)
    assert accountant.team_costs(team, 0) == 12 * UNIT
    assert accountant.global_costs(0) == 12 * UNIT

    # refund reduces costs at the average price
    token.approve(distributor, UNIT, sender=team)
    assert distributor.refund(0, UNIT, sender=team).return_value == (0, 4 * UNIT)
    assert distributor.costs(team, 0, token) == (2 * UNIT, 4 * UNIT)
    assert accountant.team_costs(team, 0) == 8 * UNIT
    assert accountant.global_costs(0) == 8 * UNIT

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

def test_set_management(deployer, alice, distributor):
    # management can propose a replacement
    assert distributor.management() == deployer
    assert distributor.pending_management() == ZERO_ADDRESS
    distributor.set_management(alice, sender=deployer)
    assert distributor.management() == deployer
    assert distributor.pending_management() == alice

def test_set_management_undo(deployer, alice, distributor):
    # proposed replacement can be undone
    distributor.set_management(alice, sender=deployer)
    distributor.set_management(ZERO_ADDRESS, sender=deployer)
    assert distributor.management() == deployer
    assert distributor.pending_management() == ZERO_ADDRESS

def test_set_management_permission(alice, distributor):
    # only management can propose a replacement
    with reverts():
        distributor.set_management(alice, sender=alice)

def test_accept_management(deployer, alice, distributor):
    # replacement can accept management role
    distributor.set_management(alice, sender=deployer)
    distributor.accept_management(sender=alice)
    assert distributor.management() == alice
    assert distributor.pending_management() == ZERO_ADDRESS

def test_accept_management_early(alice, distributor):
    # cant accept management role without being nominated
    with reverts():
        distributor.accept_management(sender=alice)

def test_accept_management_wrong(deployer, alice, bob, distributor):
    # cant accept management role without being the nominee
    distributor.set_management(alice, sender=deployer)
    with reverts():
        distributor.accept_management(sender=bob)
