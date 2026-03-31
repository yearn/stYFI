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
def factory(project, deployer, alice):
    factory = project.MockFactory.deploy(sender=deployer)
    factory.set_deployed(alice, True, sender=deployer)
    return factory

@fixture
def registry(chain, project, deployer, genesis, factory):
    chain.pending_timestamp = genesis
    registry = project.TeamRegistry.deploy(genesis, sender=deployer)
    registry.set_factory(factory, sender=deployer)
    return registry

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

def test_deposit(deployer, alice, token, registry, accountant, recipient, oracle):
    period = 0
    oracle.set_price(token, 2 * UNIT, sender=deployer)
    recipient.set_price_oracle(token, oracle, sender=deployer)
    registry.add_team(alice, sender=deployer)

    token.mint(alice, 3 * UNIT, sender=deployer)
    token.approve(recipient, 3 * UNIT, sender=alice)

    # do a deposit
    assert token.balanceOf(alice) == 3 * UNIT
    assert token.balanceOf(recipient) == 0
    assert accountant.global_revenues(period) == 0
    assert accountant.team_revenues(alice, period) == 0
    assert recipient.deposit(token, UNIT, sender=alice).return_value == (0, 2 * UNIT)
    assert token.balanceOf(alice) == 2 * UNIT
    assert token.balanceOf(recipient) == UNIT
    assert accountant.global_revenues(period) == 2 * UNIT
    assert accountant.team_revenues(alice, period) == 2 * UNIT

    # do another deposit after price has changed
    oracle.set_price(token, 3 * UNIT, sender=deployer)
    assert recipient.deposit(token, 2 * UNIT, sender=alice).return_value == (0, 6 * UNIT)
    assert token.balanceOf(alice) == 0
    assert token.balanceOf(recipient) == 3 * UNIT
    assert accountant.global_revenues(period) == 8 * UNIT
    assert accountant.team_revenues(alice, period) == 8 * UNIT

def test_deposit_convert(project, deployer, alice, token, vault, registry, accountant, recipient, oracle):
    period = 0
    token.set_decimals(6, sender=deployer)
    vault.set_scale(2, sender=deployer)
    oracle = project.RevenueOracle.deploy(vault, sender=deployer)

    assert oracle.price(token, sender=deployer).return_value == 10**30
    assert oracle.price(vault, sender=deployer).return_value == 2 * 10**30
    
    recipient.set_price_oracle(token, oracle, sender=deployer)
    recipient.set_price_oracle(vault, oracle, sender=deployer)
    recipient.set_token_converter(token, oracle, sender=deployer)

    registry.add_team(alice, sender=deployer)

    # deposit the base token
    token.mint(alice, 8 * SMALL_UNIT, sender=deployer)
    token.approve(recipient, 2 * SMALL_UNIT, sender=alice)
    assert vault.balanceOf(recipient) == 0
    assert recipient.deposit(token, 2 * SMALL_UNIT, sender=alice).return_value == (0, 2 * UNIT)
    assert vault.balanceOf(recipient) == SMALL_UNIT
    assert accountant.global_revenues(period) == 2 * UNIT

    # deposit the vault token
    token.approve(vault, 6 * SMALL_UNIT, sender=alice)
    vault.deposit(6 * SMALL_UNIT, alice, sender=alice)
    assert vault.balanceOf(alice) == 3 * SMALL_UNIT
    vault.approve(recipient, 3 * SMALL_UNIT, sender=alice)
    assert recipient.deposit(vault, 3 * SMALL_UNIT, sender=alice).return_value == (0, 6 * UNIT)
    assert vault.balanceOf(recipient) == 4 * SMALL_UNIT
    assert accountant.global_revenues(period) == 8 * UNIT
