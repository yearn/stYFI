from ape import project, reverts, Contract
from pytest import fixture

YCHAD = "0xFEB4acf3df3cDEA7399794D0869ef76A6EfAff52"

SDYFI_GAUGE = "0x5AdF559f5D24aaCbE4FA3A3a4f44Fdc7431E6b52"
SUPYFI = "0xCb7DCe63aBE175cA354Dcca9cc10554D255777Ee"
COVEYFI_GAUGE = "0x48302Ba7bCdF2bD59D20F8893C0F11b431A3be24"

VEST_FACTORY = "0x850De8D7d65A7b7D5bc825ba29543f41B8E8aFd2"
VEST_STAKEDAO = "0xEA61Ab776852695461f5A0405CC0C28BFE5ff21B"
VEST_1UP = "0xb20004a6c562ccF666962Ce5e0e3fDcC086f41ca"
VEST_COVE = "0xD4Dc463c047141f87e02Be8281Ecc811458ec583"

STREAM_DURATION = 14 * 24 * 60 * 60
UNIT = 10**18
UNIT_1UP = 69_420 * UNIT

@fixture
def ychad(accounts):
    return accounts[YCHAD]

@fixture
def mock_operator(deployer):
    return project.MockOperator.deploy(sender=deployer)

@fixture
def whitelist(deployer):
    return project.VestingStakerOperatorWhitelist.deploy(sender=deployer)

def test_1up(accounts, chain, networks, deployer, ychad, mock_operator, whitelist):
    vest = Contract(VEST_1UP)
    token = Contract(SUPYFI)
    assert vest.token() == token

    staker = project.VestingStaker1UP.deploy(vest, whitelist, sender=deployer)
    depositor = project.LiquidLockerDepositor.at(staker.DEPOSITOR())

    factory = Contract(VEST_FACTORY)
    factory.set_operator(token, staker, True, sender=ychad)

    recipient = accounts[vest.recipient()]
    networks.active_provider.set_balance(recipient.address, UNIT)
    vest.set_operator(staker, True, sender=recipient)

    # stake
    pre = token.balanceOf(vest)
    staker.stake(UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == UNIT
    assert pre - token.balanceOf(vest) == UNIT_1UP

    # stake more
    staker.stake(2 * UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == 3 * UNIT

    # unstake
    ts = chain.pending_timestamp
    staker.unstake(2 * UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == UNIT

    # claim
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    pre = token.balanceOf(vest)
    staker.claim(sender=recipient)
    assert token.balanceOf(vest) - pre == UNIT_1UP

    # claim more
    chain.pending_timestamp += STREAM_DURATION
    pre = token.balanceOf(vest)
    staker.claim(sender=recipient)
    assert token.balanceOf(vest) - pre == UNIT_1UP

    # cant add non-whitelisted operator
    staker.unstake(UNIT, sender=recipient)
    with reverts():
        staker.set_operator(mock_operator, True, sender=recipient)

    # cant call operator before adding it
    chain.pending_timestamp += STREAM_DURATION
    with reverts():
        mock_operator.redeem(staker, depositor, UNIT, sender=deployer)

    # add operator
    whitelist.set_whitelist(vest, mock_operator, True, sender=ychad)
    staker.set_operator(mock_operator, True, sender=recipient)

    # call operator
    chain.pending_timestamp += STREAM_DURATION
    mock_operator.redeem(staker, depositor, UNIT, sender=deployer)
    assert token.balanceOf(deployer) == UNIT_1UP

def test_cove(accounts, chain, networks, deployer, ychad, mock_operator, whitelist):
    vest = Contract(VEST_COVE)
    gauge = Contract(COVEYFI_GAUGE)
    assert vest.token() == gauge
    token = Contract(gauge.asset())

    staker = project.VestingStakerCove.deploy(vest, whitelist, sender=deployer)
    depositor = project.LiquidLockerDepositor.at(staker.DEPOSITOR())

    factory = Contract(VEST_FACTORY)
    factory.set_operator(gauge, staker, True, sender=ychad)

    recipient = accounts[vest.recipient()]
    networks.active_provider.set_balance(recipient.address, UNIT)
    vest.set_operator(staker, True, sender=recipient)

    # stake
    pre = gauge.balanceOf(vest)
    staker.stake(UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == UNIT
    assert pre - gauge.balanceOf(vest) == UNIT

    # stake more
    staker.stake(2 * UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == 3 * UNIT

    # unstake
    ts = chain.pending_timestamp
    staker.unstake(2 * UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == UNIT

    # claim
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    pre = gauge.balanceOf(vest)
    staker.claim(sender=recipient)
    assert gauge.balanceOf(vest) - pre == UNIT

    # claim more
    chain.pending_timestamp += STREAM_DURATION
    pre = gauge.balanceOf(vest)
    staker.claim(sender=recipient)
    assert gauge.balanceOf(vest) - pre == UNIT

    # cant add non-whitelisted operator
    staker.unstake(UNIT, sender=recipient)
    with reverts():
        staker.set_operator(mock_operator, True, sender=recipient)

    # cant call operator before adding it
    chain.pending_timestamp += STREAM_DURATION
    with reverts():
        mock_operator.redeem(staker, depositor, UNIT, sender=deployer)

    # add operator
    whitelist.set_whitelist(vest, mock_operator, True, sender=ychad)
    staker.set_operator(mock_operator, True, sender=recipient)

    # call operator
    chain.pending_timestamp += STREAM_DURATION
    mock_operator.redeem(staker, depositor, UNIT, sender=deployer)
    assert token.balanceOf(deployer) == UNIT

def test_stakedao(accounts, chain, networks, deployer, ychad, mock_operator, whitelist):
    vest = Contract(VEST_STAKEDAO)
    gauge = Contract(SDYFI_GAUGE)
    assert vest.token() == gauge
    token = Contract(gauge.staking_token())

    staker = project.VestingStakerStakeDAO.deploy(vest, whitelist, sender=deployer)
    depositor = project.LiquidLockerDepositor.at(staker.DEPOSITOR())

    factory = Contract(VEST_FACTORY)
    factory.set_operator(gauge, staker, True, sender=ychad)

    recipient = accounts[vest.recipient()]
    networks.active_provider.set_balance(recipient.address, UNIT)
    vest.set_operator(staker, True, sender=recipient)

    # stake
    pre = gauge.balanceOf(vest)
    staker.stake(UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == UNIT
    assert pre - gauge.balanceOf(vest) == UNIT

    # stake more
    staker.stake(2 * UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == 3 * UNIT

    # unstake
    ts = chain.pending_timestamp
    staker.unstake(2 * UNIT, sender=recipient)
    assert depositor.balanceOf(staker) == UNIT

    # claim
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    pre = gauge.balanceOf(vest)
    staker.claim(sender=recipient)
    assert gauge.balanceOf(vest) - pre == UNIT

    # claim more
    chain.pending_timestamp += STREAM_DURATION
    pre = gauge.balanceOf(vest)
    staker.claim(sender=recipient)
    assert gauge.balanceOf(vest) - pre == UNIT

    # cant add non-whitelisted operator
    staker.unstake(UNIT, sender=recipient)
    with reverts():
        staker.set_operator(mock_operator, True, sender=recipient)

    # cant call operator before adding it
    chain.pending_timestamp += STREAM_DURATION
    with reverts():
        mock_operator.redeem(staker, depositor, UNIT, sender=deployer)

    # add operator
    whitelist.set_whitelist(vest, mock_operator, True, sender=ychad)
    staker.set_operator(mock_operator, True, sender=recipient)

    # call operator
    chain.pending_timestamp += STREAM_DURATION
    mock_operator.redeem(staker, depositor, UNIT, sender=deployer)
    assert token.balanceOf(deployer) == UNIT
