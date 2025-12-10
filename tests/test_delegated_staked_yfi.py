from ape import reverts
from pytest import fixture

ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'
UNIT = 10**18
BIG_MASK = 2**112 - 1
STREAM_DURATION = 14 * 24 * 60 * 60

@fixture
def hooks(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def staking(project, deployer, yfi, hooks):
    staking = project.StakedYFI.deploy(yfi, sender=deployer)
    staking.set_hooks(hooks, sender=deployer)
    return staking

@fixture
def dhooks(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def dstaking(project, deployer, hooks, staking, dhooks):
    dstaking = project.DelegatedStakedYFI.deploy(staking, sender=deployer)
    dstaking.set_hooks(dhooks, sender=deployer)
    hooks.set_instant_withdrawal(dstaking, True, sender=deployer)
    return dstaking

def test_deposit(deployer, alice, bob, yfi, staking, dstaking):
    # depositing increases supply and user balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(dstaking, UNIT, sender=alice)
    assert yfi.balanceOf(staking) == 0
    assert yfi.balanceOf(dstaking) == 0
    assert dstaking.totalSupply() == 0
    assert dstaking.balanceOf(bob) == 0
    dstaking.deposit(UNIT, bob, sender=alice)
    assert yfi.balanceOf(staking) == UNIT
    assert yfi.balanceOf(dstaking) == 0
    assert dstaking.totalSupply() == UNIT
    assert dstaking.balanceOf(bob) == UNIT

def test_deposit_add(deployer, alice, yfi, staking, dstaking):
    # depositing adds to supply and user balance
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(dstaking, 3 * UNIT, sender=alice)
    dstaking.deposit(UNIT, sender=alice)
    dstaking.deposit(2 * UNIT, sender=alice)
    assert yfi.balanceOf(staking) == 3 * UNIT
    assert dstaking.totalSupply() == 3 * UNIT
    assert dstaking.balanceOf(alice) == 3 * UNIT

def test_deposit_multiple(deployer, alice, bob, yfi, staking, dstaking):
    # deposits from multiple users updates supply and balance as expected
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(dstaking, UNIT, sender=alice)
    dstaking.deposit(UNIT, sender=alice)
    yfi.mint(bob, 2 * UNIT, sender=deployer)
    yfi.approve(dstaking, 2 * UNIT, sender=bob)
    dstaking.deposit(2 * UNIT, sender=bob)
    assert yfi.balanceOf(staking) == 3 * UNIT
    assert dstaking.totalSupply() == 3 * UNIT
    assert dstaking.balanceOf(alice) == UNIT
    assert dstaking.balanceOf(bob) == 2 * UNIT

def test_deposit_excessive(deployer, alice, yfi, dstaking):
    # cant deposit more than the balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(dstaking, UNIT, sender=alice)
    with reverts():
        dstaking.deposit(2 * UNIT, sender=alice)

def test_unstake(chain, deployer, alice, yfi, dstaking):
    # unstaking starts a stream
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(dstaking, 3 * UNIT, sender=alice)
    dstaking.deposit(3 * UNIT, sender=alice)
    assert dstaking.streams(alice) == (0, 0, 0)
    assert yfi.balanceOf(dstaking) == 0
    ts = chain.pending_timestamp
    dstaking.unstake(2 * UNIT, sender=alice)
    assert yfi.balanceOf(dstaking) == 2 * UNIT
    assert dstaking.totalSupply() == UNIT
    assert dstaking.balanceOf(alice) == UNIT
    assert dstaking.streams(alice) == (ts, 2 * UNIT, 0)

def test_unstake_excessive(deployer, alice, yfi, dstaking):
    # cant unstake more than balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(dstaking, UNIT, sender=alice)
    dstaking.deposit(UNIT, sender=alice)
    with reverts():
        dstaking.unstake(2 * UNIT, sender=alice)

def test_unstake_withdraw(chain, deployer, alice, bob, yfi, dstaking):
    # once a stream is active, tokens can be withdrawn over time
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    dstaking.unstake(4 * UNIT, sender=alice)
    assert dstaking.maxWithdraw(alice) == 0
    chain.pending_timestamp = ts + STREAM_DURATION // 4
    with chain.isolate():
        chain.mine()
        assert dstaking.maxWithdraw(alice) == UNIT
    with chain.isolate():
        dstaking.withdraw(UNIT, bob, sender=alice)
        assert dstaking.streams(alice) == (ts, 4 * UNIT, UNIT)
        assert dstaking.maxWithdraw(alice) == 0
        assert yfi.balanceOf(bob) == UNIT
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    with chain.isolate():
        chain.mine()
        assert dstaking.maxWithdraw(alice) == 2 * UNIT
    with chain.isolate():
        dstaking.withdraw(2 * UNIT, bob, sender=alice)
        assert dstaking.streams(alice) == (ts, 4 * UNIT, 2 * UNIT)
        assert dstaking.maxWithdraw(alice) == 0
        assert yfi.balanceOf(bob) == 2 * UNIT

def test_unstake_withdraw_multiple(chain, deployer, alice, yfi, dstaking):
    # can withdraw multiple times from the stream
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    dstaking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 4
    dstaking.withdraw(UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION * 3 // 4
    with chain.isolate():
        chain.mine()
        assert dstaking.maxWithdraw(alice) == 2 * UNIT
    dstaking.withdraw(UNIT, sender=alice)
    assert dstaking.streams(alice) == (ts, 4 * UNIT, 2 * UNIT)
    assert dstaking.maxWithdraw(alice) == UNIT
    assert yfi.balanceOf(alice) == 2 * UNIT

def test_unstake_withdraw_excessive(chain, deployer, alice, yfi, dstaking):
    # cant withdraw more than has been streamed
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    dstaking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 4
    with reverts():
        dstaking.withdraw(2 * UNIT, sender=alice)

def test_unstake_withdraw_all(chain, deployer, alice, yfi, dstaking):
    # after stream has ended the full amount can be withdrawn
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    dstaking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp = ts + 2 * STREAM_DURATION
    chain.mine()
    assert dstaking.maxWithdraw(alice) == 4 * UNIT
    dstaking.withdraw(4 * UNIT, sender=alice)
    assert dstaking.maxWithdraw(alice) == 0

def test_unstake_withdraw_from(chain, deployer, alice, bob, yfi, dstaking):
    # third party with allowance can withdraw from a stream
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    dstaking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp += STREAM_DURATION
    dstaking.approve(bob, 3 * UNIT, sender=alice)
    assert dstaking.allowance(alice, bob) == 3 * UNIT
    dstaking.withdraw(UNIT, deployer, alice, sender=bob)
    assert dstaking.maxWithdraw(alice) == 3 * UNIT
    assert dstaking.allowance(alice, bob) == 2 * UNIT
    assert yfi.balanceOf(deployer) == UNIT

def test_unstake_withdraw_from_excessive(chain, deployer, alice, bob, yfi, dstaking):
    # third party cant withdraw more than has been streamed
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    dstaking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    dstaking.approve(bob, 3 * UNIT, sender=alice)
    with reverts():
        dstaking.withdraw(3 * UNIT, deployer, alice, sender=bob)

def test_unstake_withdraw_from_allowance(chain, deployer, alice, bob, yfi, dstaking):
    # third party cant withdraw more than their allowance
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    dstaking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp += STREAM_DURATION
    dstaking.approve(bob, UNIT, sender=alice)
    with reverts():
        dstaking.withdraw(2 * UNIT, deployer, alice, sender=bob)

def test_unstake_merge(chain, deployer, alice, yfi, dstaking):
    # unstaking with an existing stream adds unclaimed into the new one
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    dstaking.unstake(3 * UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION * 3 // 4
    dstaking.withdraw(2 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    dstaking.unstake(UNIT, sender=alice)
    assert dstaking.streams(alice) == (ts, 2 * UNIT, 0)
    assert dstaking.maxWithdraw(alice) == 0

def test_transfer(deployer, alice, bob, yfi, staking, dstaking):
    # transferring updates balances but not supply
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(dstaking, 3 * UNIT, sender=alice)
    dstaking.deposit(3 * UNIT, sender=alice)
    dstaking.transfer(bob, UNIT, sender=alice)
    assert yfi.balanceOf(staking) == 3 * UNIT
    assert dstaking.totalSupply() == 3 * UNIT
    assert dstaking.balanceOf(alice) == 2 * UNIT
    assert dstaking.balanceOf(bob) == UNIT

def test_transfer_excessive(deployer, alice, bob, yfi, dstaking):
    # cant transfer more than balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(dstaking, UNIT, sender=alice)
    dstaking.deposit(UNIT, sender=alice)
    with reverts():
        dstaking.transfer(bob, 2 * UNIT, sender=alice)

def test_transfer_from(deployer, alice, bob, yfi, staking, dstaking):
    # can transfer from other users if there's an allowance
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(dstaking, 4 * UNIT, sender=alice)
    dstaking.deposit(4 * UNIT, sender=alice)
    dstaking.approve(deployer, 3 * UNIT, sender=alice)
    dstaking.transferFrom(alice, bob, UNIT, sender=deployer)
    assert yfi.balanceOf(staking) == 4 * UNIT
    assert dstaking.allowance(alice, deployer) == 2 * UNIT
    assert dstaking.totalSupply() == 4 * UNIT
    assert dstaking.balanceOf(alice) == 3 * UNIT
    assert dstaking.balanceOf(bob) == UNIT

def test_transfer_from_excessive(deployer, alice, bob, yfi, dstaking):
    # cant transfer more from other user than the balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(dstaking, UNIT, sender=alice)
    dstaking.deposit(UNIT, sender=alice)
    dstaking.approve(bob, 2 * UNIT, sender=alice)
    with reverts():
        dstaking.transferFrom(alice, bob, 2 * UNIT, sender=bob)

def test_transfer_from_allowance_excessive(deployer, alice, bob, yfi, dstaking):
    # cant transfer more from other user than the allowance
    yfi.mint(alice, 2 * UNIT, sender=deployer)
    yfi.approve(dstaking, 2 * UNIT, sender=alice)
    dstaking.deposit(2 * UNIT, sender=alice)
    dstaking.approve(bob, UNIT, sender=alice)
    with reverts():
        dstaking.transferFrom(alice, bob, 2 * UNIT, sender=bob)

def test_approve(alice, bob, dstaking):
    # set allowance
    assert dstaking.allowance(alice, bob) == 0
    dstaking.approve(bob, UNIT, sender=alice)
    assert dstaking.allowance(alice, bob) == UNIT

def test_transfer_hook(deployer, alice, bob, yfi, dhooks, dstaking):
    # transfering triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(dstaking, 3 * UNIT, sender=alice)
    dstaking.deposit(3 * UNIT, sender=alice)

    assert dhooks.last_transfer() == (ZERO_ADDRESS, ZERO_ADDRESS, ZERO_ADDRESS, 0, 0, 0, 0)
    dstaking.transfer(bob, UNIT, sender=alice)
    assert dhooks.last_transfer() == (alice, alice, bob, 3 * UNIT, 3 * UNIT, 0, UNIT)
    dstaking.transfer(bob, UNIT, sender=alice)
    assert dhooks.last_transfer() == (alice, alice, bob, 3 * UNIT, 2 * UNIT, UNIT, UNIT)

def test_transfer_from_hook(deployer, alice, bob, yfi, dhooks, dstaking):
    # transfering with allowance triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(dstaking, 3 * UNIT, sender=alice)
    dstaking.deposit(3 * UNIT, sender=alice)
    dstaking.approve(bob, 2 * UNIT, sender=alice)

    assert dhooks.last_transfer() == (ZERO_ADDRESS, ZERO_ADDRESS, ZERO_ADDRESS, 0, 0, 0, 0)
    dstaking.transferFrom(alice, bob, UNIT, sender=bob)
    assert dhooks.last_transfer() == (bob, alice, bob, 3 * UNIT, 3 * UNIT, 0, UNIT)
    dstaking.transferFrom(alice, bob, UNIT, sender=bob)
    assert dhooks.last_transfer() == (bob, alice, bob, 3 * UNIT, 2 * UNIT, UNIT, UNIT)

def test_stake_hook(deployer, alice, bob, yfi, dhooks, dstaking):
    # staking triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(dstaking, 3 * UNIT, sender=alice)

    assert dhooks.last_stake() == (ZERO_ADDRESS, ZERO_ADDRESS, 0, 0, 0)
    dstaking.deposit(2 * UNIT, sender=alice)
    assert dhooks.last_stake() == (alice, alice, 0, 0, 2 * UNIT)
    dstaking.deposit(UNIT, sender=alice)
    assert dhooks.last_stake() == (alice, alice, 2 * UNIT, 2 * UNIT, UNIT)

    yfi.mint(bob, UNIT, sender=deployer)
    yfi.approve(dstaking, UNIT, sender=bob)
    dstaking.deposit(UNIT, sender=bob)
    assert dhooks.last_stake() == (bob, bob, 3 * UNIT, 0, UNIT)

def test_stake_for_hook(deployer, alice, bob, yfi, dhooks, dstaking):
    # staking for someone else triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(dstaking, 3 * UNIT, sender=alice)

    assert dhooks.last_stake() == (ZERO_ADDRESS, ZERO_ADDRESS, 0, 0, 0)
    dstaking.deposit(2 * UNIT, bob, sender=alice)
    assert dhooks.last_stake() == (alice, bob, 0, 0, 2 * UNIT)
    dstaking.deposit(UNIT, bob, sender=alice)
    assert dhooks.last_stake() == (alice, bob, 2 * UNIT, 2 * UNIT, UNIT)

def test_unstake_hook(deployer, alice, bob, yfi, dhooks, dstaking):
    # unstaking triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(dstaking, 3 * UNIT, sender=alice)
    dstaking.deposit(3 * UNIT, sender=alice)

    assert dhooks.last_unstake() == (ZERO_ADDRESS, 0, 0, 0)
    dstaking.unstake(UNIT, sender=alice)
    assert dhooks.last_unstake() == (alice, 3 * UNIT, 3 * UNIT, UNIT)

    yfi.mint(bob, UNIT, sender=deployer)
    yfi.approve(dstaking, UNIT, sender=bob)
    dstaking.deposit(UNIT, sender=bob)

    dstaking.unstake(UNIT, sender=alice)
    assert dhooks.last_unstake() == (alice, 3 * UNIT, 2 * UNIT, UNIT)

def test_set_hooks(project, deployer, dstaking, dhooks):
    # hooks contract can be changed
    dhooks2 = project.MockHooks.deploy(sender=deployer)
    assert dstaking.hooks() == dhooks
    dstaking.set_hooks(dhooks2, sender=deployer)
    assert dstaking.hooks() == dhooks2

def test_set_hooks_permission(project, deployer, alice, dstaking):
    # only management can change rewards contract
    hooks2 = project.MockHooks.deploy(sender=deployer)
    with reverts():
        dstaking.set_hooks(hooks2, sender=alice)

def test_set_management(deployer, alice, dstaking):
    # management can propose a replacement
    assert dstaking.management() == deployer
    assert dstaking.pending_management() == ZERO_ADDRESS
    dstaking.set_management(alice, sender=deployer)
    assert dstaking.management() == deployer
    assert dstaking.pending_management() == alice

def test_set_management_undo(deployer, alice, dstaking):
    # proposed replacement can be undone
    dstaking.set_management(alice, sender=deployer)
    dstaking.set_management(ZERO_ADDRESS, sender=deployer)
    assert dstaking.management() == deployer
    assert dstaking.pending_management() == ZERO_ADDRESS

def test_set_management_permission(alice, dstaking):
    # only management can propose a replacement
    with reverts():
        dstaking.set_management(alice, sender=alice)

def test_accept_management(deployer, alice, dstaking):
    # replacement can accept management role
    dstaking.set_management(alice, sender=deployer)
    dstaking.accept_management(sender=alice)
    assert dstaking.management() == alice
    assert dstaking.pending_management() == ZERO_ADDRESS

def test_accept_management_early(alice, dstaking):
    # cant accept management role without being nominated
    with reverts():
        dstaking.accept_management(sender=alice)

def test_accept_management_wrong(deployer, alice, bob, dstaking):
    # cant accept management role without being the nominee
    dstaking.set_management(alice, sender=deployer)
    with reverts():
        dstaking.accept_management(sender=bob)
