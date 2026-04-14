from ape import reverts, Contract
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
def recipient(project, deployer, genesis, vault, registry, accountant):
    recipient = project.RevenueRecipient.deploy(genesis, vault, [8000, 1000, 1000], sender=deployer)
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

def test_to_styfi(chain, project, deployer, alice, genesis, token, vault, recipient):
    distributor = project.RewardDistributor.deploy(genesis, vault, sender=deployer)
    recipient.set_reward_distributor(distributor, sender=deployer)
    recipient.set_operator(alice, sender=deployer)

    token.mint(deployer, 12 * UNIT, sender=deployer)
    token.approve(vault, 12 * UNIT, sender=deployer)
    vault.deposit(10 * UNIT, recipient, sender=deployer)

    assert recipient.last_balance() == 0
    assert recipient.sum_balance() == 0
    assert recipient.used(0) == 0
    assert vault.balanceOf(distributor) == 0

    # we can send 80% of all tokens to stYFI in one or multiple steps
    with chain.isolate():
        recipient.to_styfi_rewards(0, 8 * UNIT, sender=alice)
        assert recipient.last_balance() == 2 * UNIT
        assert recipient.sum_balance() == 10 * UNIT
        assert recipient.used(0) == 8 * UNIT
        assert vault.balanceOf(distributor) == 8 * UNIT

    with chain.isolate():
        recipient.to_styfi_rewards(0, 4 * UNIT, sender=alice)
        assert recipient.last_balance() == 6 * UNIT
        assert recipient.sum_balance() == 10 * UNIT
        assert recipient.used(0) == 4 * UNIT
        assert vault.balanceOf(distributor) == 4 * UNIT
        recipient.to_styfi_rewards(1, 4 * UNIT, sender=alice)
        assert recipient.last_balance() == 2 * UNIT
        assert recipient.sum_balance() == 10 * UNIT
        assert recipient.used(0) == 8 * UNIT
        assert vault.balanceOf(distributor) == 8 * UNIT

    # additional deposits are counted properly
    with chain.isolate():
        recipient.to_styfi_rewards(0, 4 * UNIT, sender=alice)
        vault.deposit(2 * UNIT, recipient, sender=deployer)
        recipient.to_styfi_rewards(1, 4 * UNIT, sender=alice)
        assert recipient.last_balance() == 4 * UNIT
        assert recipient.sum_balance() == 12 * UNIT
        assert recipient.used(0) == 8 * UNIT
        assert vault.balanceOf(distributor) == 8 * UNIT

    # but we cant send 80% + 1
    with reverts():
        recipient.to_styfi_rewards(0, 8 * UNIT + 1, sender=alice)

def test_to_treasury(chain, deployer, alice, bob, token, vault, recipient):
    recipient.set_operator(alice, sender=deployer)
    recipient.set_treasury(bob, sender=deployer)

    token.mint(deployer, 20 * UNIT, sender=deployer)
    token.approve(vault, 20 * UNIT, sender=deployer)
    vault.deposit(20 * UNIT, recipient, sender=deployer)

    assert recipient.last_balance() == 0
    assert recipient.sum_balance() == 0
    assert recipient.used(1) == 0
    assert vault.balanceOf(bob) == 0

    # we can send 10% of all tokens to treasury in one or multiple steps
    with chain.isolate():
        recipient.to_treasury(2 * UNIT, sender=alice)
        assert recipient.last_balance() == 18 * UNIT
        assert recipient.sum_balance() == 20 * UNIT
        assert recipient.used(1) == 2 * UNIT
        assert vault.balanceOf(bob) == 2 * UNIT

    with chain.isolate():
        recipient.to_treasury(UNIT, sender=alice)
        assert recipient.last_balance() == 19 * UNIT
        assert recipient.sum_balance() == 20 * UNIT
        assert recipient.used(1) == UNIT
        assert vault.balanceOf(bob) == UNIT
        recipient.to_treasury(UNIT, sender=alice)
        assert recipient.last_balance() == 18 * UNIT
        assert recipient.sum_balance() == 20 * UNIT
        assert recipient.used(1) == 2 * UNIT
        assert vault.balanceOf(bob) == 2 * UNIT

    # but we cant send 10% + 1
    with reverts():
        recipient.to_treasury(2 * UNIT + 1, sender=alice)

# # the following tests can only be ran with `--network ethereum:mainnet-fork` flag:
# def test_to_yeth(chain, project, deployer, alice, bob, token, vault, recipient):
#     factory = Contract("0xbC587a495420aBB71Bbd40A0e291B64e80117526")
#     auction = factory.createNewAuction("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", bob, sender=deployer).return_value
#     auction = project.MockAuction.at(auction)
#     auction.enable(vault, sender=deployer)

#     recipient.set_operator(alice, sender=deployer)
#     recipient.set_recovery_auction(auction, sender=deployer)

#     token.mint(deployer, 20 * UNIT, sender=deployer)
#     token.approve(vault, 20 * UNIT, sender=deployer)
#     vault.deposit(20 * UNIT, recipient, sender=deployer)

#     assert recipient.last_balance() == 0
#     assert recipient.sum_balance() == 0
#     assert recipient.used(1) == 0
#     assert vault.balanceOf(bob) == 0

#     # we can send 10% of all tokens to recovery
#     with chain.isolate():
#         recipient.to_yeth_recovery(2 * UNIT, sender=alice)
#         assert recipient.last_balance() == 18 * UNIT
#         assert recipient.sum_balance() == 20 * UNIT
#         assert recipient.used(2) == 2 * UNIT
#         assert vault.balanceOf(auction) == 2 * UNIT

#     # but we cant send 10% + 1
#     with reverts():
#         recipient.to_yeth_recovery(2 * UNIT + 1, sender=alice)
