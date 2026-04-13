from pytest import fixture

PERIOD_LENGTH = 6 * 14 * 24 * 60 * 60
UNIT = 10**18
SMALL_UNIT = 10**6

@fixture
def token(project, deployer):
    return project.MockToken.deploy(sender=deployer)

@fixture
def vault(project, deployer, token):
    return project.MockVault.deploy(token, sender=deployer)

@fixture
def implementation(project, deployer):
    return project.Team.deploy(sender=deployer)

@fixture
def registry(chain, project, deployer, genesis, implementation):
    chain.pending_timestamp = genesis
    registry = project.TeamRegistry.deploy(genesis, sender=deployer)
    registry.set_implementation(implementation, sender=deployer)
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
def recipient(project, deployer, genesis, registry, accountant):
    recipient = project.RevenueRecipient.deploy(genesis, sender=deployer)
    recipient.set_registry(registry, sender=deployer)
    recipient.set_accountant(accountant, sender=deployer)
    accountant.set_operator(recipient, True, sender=deployer)
    return recipient

@fixture
def oracle(project, deployer):
    return project.MockOracle.deploy(sender=deployer)

def test_deposit(deployer, token, accountant, recipient, oracle, team):
    period = 0
    oracle.set_price(token, 2 * UNIT, sender=deployer)
    recipient.set_price_oracle(token, oracle, sender=deployer)

    token.mint(team, 3 * UNIT, sender=deployer)
    token.approve(recipient, 3 * UNIT, sender=team)

    # do a deposit
    assert token.balanceOf(team) == 3 * UNIT
    assert token.balanceOf(recipient) == 0
    assert accountant.global_revenues(period) == 0
    assert accountant.team_revenues(team, period) == 0
    assert recipient.deposit(token, UNIT, sender=team).return_value == (0, 2 * UNIT)
    assert token.balanceOf(team) == 2 * UNIT
    assert token.balanceOf(recipient) == UNIT
    assert accountant.global_revenues(period) == 2 * UNIT
    assert accountant.team_revenues(team, period) == 2 * UNIT

    # do another deposit after price has changed
    oracle.set_price(token, 3 * UNIT, sender=deployer)
    assert recipient.deposit(token, 2 * UNIT, sender=team).return_value == (0, 6 * UNIT)
    assert token.balanceOf(team) == 0
    assert token.balanceOf(recipient) == 3 * UNIT
    assert accountant.global_revenues(period) == 8 * UNIT
    assert accountant.team_revenues(team, period) == 8 * UNIT

def test_deposit_convert(project, deployer, token, vault, accountant, recipient, oracle, team):
    period = 0
    token.set_decimals(6, sender=deployer)
    vault.set_scale(2, sender=deployer)
    oracle = project.RevenueOracle.deploy(vault, sender=deployer)

    assert oracle.price(token, sender=deployer).return_value == 10**30
    assert oracle.price(vault, sender=deployer).return_value == 2 * 10**30
    
    recipient.set_price_oracle(token, oracle, sender=deployer)
    recipient.set_price_oracle(vault, oracle, sender=deployer)
    recipient.set_token_converter(token, oracle, sender=deployer)

    # deposit the base token
    token.mint(team, 8 * SMALL_UNIT, sender=deployer)
    token.approve(recipient, 2 * SMALL_UNIT, sender=team)
    assert vault.balanceOf(recipient) == 0
    assert recipient.deposit(token, 2 * SMALL_UNIT, sender=team).return_value == (0, 2 * UNIT)
    assert vault.balanceOf(recipient) == SMALL_UNIT
    assert accountant.global_revenues(period) == 2 * UNIT

    # deposit the vault token
    token.approve(vault, 6 * SMALL_UNIT, sender=team)
    vault.deposit(6 * SMALL_UNIT, team, sender=team)
    assert vault.balanceOf(team) == 3 * SMALL_UNIT
    vault.approve(recipient, 3 * SMALL_UNIT, sender=team)
    assert recipient.deposit(vault, 3 * SMALL_UNIT, sender=team).return_value == (0, 6 * UNIT)
    assert vault.balanceOf(recipient) == 4 * SMALL_UNIT
    assert accountant.global_revenues(period) == 8 * UNIT
