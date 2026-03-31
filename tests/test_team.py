from ape import reverts
from pytest import fixture

UNIT = 10**18
SMALL_UNIT = 10**6
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

@fixture
def accountant(project, deployer):
    return project.TeamAccountant.deploy(sender=deployer)

@fixture
def token(project, deployer):
    token = project.MockToken.deploy(sender=deployer)
    token.set_decimals(6, sender=deployer)
    return token

@fixture
def vault(project, deployer, token):
    vault = project.MockVault.deploy(token, sender=deployer)
    vault.set_scale(2, sender=deployer)
    return vault

@fixture
def oracle(project, deployer, vault):
    return project.RevenueOracle.deploy(vault, sender=deployer)

@fixture
def distributor(project, deployer, genesis, accountant, token, vault, oracle):
    distributor = project.FundingDistributor.deploy(genesis, sender=deployer)
    distributor.set_price_oracle(token, oracle, sender=deployer)
    distributor.set_price_oracle(vault, oracle, sender=deployer)
    distributor.set_accountant(accountant, sender=deployer)
    accountant.set_operator(distributor, True, sender=deployer)
    return distributor

@fixture
def recipient(project, deployer, genesis, accountant, token, vault, oracle):
    recipient = project.RevenueRecipient.deploy(genesis, sender=deployer)
    recipient.set_price_oracle(token, oracle, sender=deployer)
    recipient.set_price_oracle(vault, oracle, sender=deployer)
    recipient.set_token_converter(token, oracle, sender=deployer)
    recipient.set_accountant(accountant, sender=deployer)
    accountant.set_operator(recipient, True, sender=deployer)
    return recipient

@fixture
def registry(chain, project, deployer, genesis, distributor, recipient):
    chain.pending_timestamp = genesis
    registry = project.TeamRegistry.deploy(genesis, sender=deployer)

    registry.set_funding_distributor(distributor, sender=deployer)
    distributor.set_registry(registry, sender=deployer)

    registry.set_revenue_recipient(recipient, sender=deployer)
    recipient.set_registry(registry, sender=deployer)

    return registry

@fixture
def implementation(project, deployer):
    return project.Team.deploy(sender=deployer)

@fixture
def factory(project, deployer, registry, implementation):
    factory = project.TeamFactory.deploy(registry, implementation, sender=deployer)
    registry.set_factory(factory, sender=deployer)
    return factory

@fixture
def team(project, deployer, alice, factory, registry):
    team = project.Team.at(factory.deploy("A", sender=alice).return_value)
    registry.add_team(team, sender=deployer)
    return team

def test_setup(deployer, registry, implementation, team):
    with reverts():
        implementation.setup("A", registry, deployer, sender=deployer)

    with reverts():
        team.setup("A", registry, deployer, sender=deployer)

def test_deposit_revenue(alice, accountant, token, vault, recipient, team):
    token.mint(alice, 6 * SMALL_UNIT, sender=alice)
    token.approve(vault, 2 * SMALL_UNIT, sender=alice)
    vault.deposit(2 * SMALL_UNIT, alice, sender=alice)
    vault.approve(team, SMALL_UNIT, sender=alice)

    # deposit vault token
    assert vault.balanceOf(recipient) == 0
    assert accountant.team_revenues(team, 0) == 0
    assert team.deposit_revenue(vault, SMALL_UNIT, sender=alice).return_value == 2 * UNIT
    assert vault.balanceOf(recipient) == SMALL_UNIT
    assert accountant.team_revenues(team, 0) == 2 * UNIT

    # deposit naked token
    token.approve(team, 4 * SMALL_UNIT, sender=alice)
    assert team.deposit_revenue(token, 4 * SMALL_UNIT, sender=alice).return_value == 4 * UNIT
    assert vault.balanceOf(recipient) == 3 * SMALL_UNIT
    assert accountant.team_revenues(team, 0) == 6 * UNIT

def test_claim_funding(deployer, alice, bob, accountant, token, vault, distributor, team):
    token.mint(deployer, 6 * SMALL_UNIT, sender=deployer)
    token.approve(vault, 6 * SMALL_UNIT, sender=deployer)
    vault.deposit(6 * SMALL_UNIT, distributor, sender=deployer)
    distributor.approve(team, 0, vault, 3 * SMALL_UNIT, 0, sender=deployer)

    assert vault.balanceOf(bob) == 0
    assert accountant.team_costs(team, 0) == 0
    assert team.claim_funding(0, SMALL_UNIT, bob, sender=alice).return_value == (vault, 2 * UNIT, ZERO_ADDRESS)
    assert vault.balanceOf(bob) == SMALL_UNIT
    assert accountant.team_costs(team, 0) == 2 * UNIT

    vault.set_scale(3, sender=deployer)
    assert team.claim_funding(0, 2 * SMALL_UNIT, sender=alice).return_value == (vault, 6 * UNIT, ZERO_ADDRESS)
    assert vault.balanceOf(alice) == 2 * SMALL_UNIT
    assert accountant.team_costs(team, 0) == 8 * UNIT

def test_return_funding(deployer, alice, accountant, token, vault, distributor, team):
    token.mint(deployer, 6 * SMALL_UNIT, sender=deployer)
    token.approve(vault, 6 * SMALL_UNIT, sender=deployer)
    vault.deposit(6 * SMALL_UNIT, distributor, sender=deployer)
    distributor.approve(team, 0, vault, 3 * SMALL_UNIT, 0, sender=deployer)
    team.claim_funding(0, 3 * SMALL_UNIT, sender=alice)
    
    # repayments are credited using the price at time of claim
    vault.set_scale(3, sender=deployer)
    vault.approve(team, SMALL_UNIT, sender=alice)
    assert team.return_funding(0, SMALL_UNIT, sender=alice).return_value == (vault, 2 * UNIT)
    assert vault.balanceOf(alice) == 2 * SMALL_UNIT
    assert accountant.team_costs(team, 0) == 4 * UNIT

def test_set_owner(alice, bob, team):
    assert team.owner() == alice
    team.set_owner(bob, sender=alice)
    assert team.owner() == bob

def test_set_owner_permission(alice, bob, team):
    with reverts():
        team.set_owner(bob, sender=bob)
    team.set_owner(bob, sender=alice)
