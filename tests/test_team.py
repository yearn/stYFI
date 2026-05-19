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
    return project.RevenuePriceOracle.deploy(vault, sender=deployer)

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
    recipient = project.RevenueRecipient.deploy(genesis, vault, [8000, 1000, 1000], sender=deployer)
    recipient.set_price_oracle(token, oracle, sender=deployer)
    recipient.set_price_oracle(vault, oracle, sender=deployer)
    recipient.set_token_converter(token, oracle, sender=deployer)
    recipient.set_accountant(accountant, sender=deployer)
    accountant.set_operator(recipient, True, sender=deployer)
    return recipient

@fixture
def implementation(project, deployer):
    return project.Team.deploy(sender=deployer)

@fixture
def registry(chain, project, deployer, genesis, distributor, recipient, implementation):
    chain.pending_timestamp = genesis
    registry = project.TeamRegistry.deploy(genesis, sender=deployer)

    registry.set_funding_distributor(distributor, sender=deployer)
    distributor.set_registry(registry, sender=deployer)

    registry.set_revenue_recipient(recipient, sender=deployer)
    recipient.set_registry(registry, sender=deployer)

    registry.set_implementation(implementation, sender=deployer)

    return registry

@fixture
def team(project, deployer, alice, registry):
    return project.Team.at(registry.add_team("A", alice, sender=deployer).return_value[1])

def test_setup(deployer, implementation, team):
    with reverts():
        implementation.setup("A", deployer, sender=deployer)

    with reverts():
        team.setup("A", deployer, sender=deployer)

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
    assert team.claim_funding(0, sender=alice).return_value == (vault, 6 * UNIT, ZERO_ADDRESS)
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

def test_sweep(project, deployer, alice, team):
    # tokens can be transfered out
    token = project.MockToken.deploy(sender=deployer)
    token.mint(team, 3 * UNIT, sender=deployer)
    assert token.balanceOf(alice) == 0
    assert token.balanceOf(team) == 3 * UNIT
    team.sweep(token, UNIT, sender=alice)
    assert token.balanceOf(alice) == UNIT
    assert token.balanceOf(team) == 2 * UNIT
    team.sweep(token, sender=alice)
    assert token.balanceOf(alice) == 3 * UNIT
    assert token.balanceOf(team) == 0

def test_sweep_permission(project, deployer, alice, bob, team):
    # only management can transfer tokens out
    token = project.MockToken.deploy(sender=deployer)
    token.mint(team, UNIT, sender=deployer)
    with reverts():
        team.sweep(token, sender=bob)
    team.sweep(token, sender=alice)

def test_set_owner(alice, bob, team):
    # owner can propose a replacement
    assert team.owner() == alice
    assert team.pending_owner() == ZERO_ADDRESS
    team.set_owner(bob, sender=alice)
    assert team.owner() == alice
    assert team.pending_owner() == bob

def test_set_owner_undo(alice, bob, team):
    # proposed replacement can be undone
    team.set_owner(bob, sender=alice)
    team.set_owner(ZERO_ADDRESS, sender=alice)
    assert team.owner() == alice
    assert team.pending_owner() == ZERO_ADDRESS

def test_set_owner_permission(bob, team):
    # only owner can propose a replacement
    with reverts():
        team.set_owner(bob, sender=bob)

def test_accept_owner(alice, bob, team):
    # replacement can accept ownership role
    team.set_owner(bob, sender=alice)
    team.accept_owner(sender=bob)
    assert team.owner() == bob
    assert team.pending_owner() == ZERO_ADDRESS

def test_accept_owner_early(bob, team):
    # cant accept ownership role without being nominated
    with reverts():
        team.accept_owner(sender=bob)

def test_accept_owner_wrong(alice, bob, charlie, team):
    # cant accept management role without being the nominee
    team.set_owner(bob, sender=alice)
    with reverts():
        team.accept_owner(sender=charlie)
