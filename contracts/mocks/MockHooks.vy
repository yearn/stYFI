# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun

interface IHooks:
    def on_transfer(_caller: address, _from: address, _to: address, _value: uint256): nonpayable
    def on_stake(_caller: address, _account: address, _value: uint256): nonpayable
    def on_unstake(_account: address, _value: uint256): nonpayable
    def instant_withdrawal(_account: address) -> bool: view

implements: IHooks

struct Transfer:
    caller: address
    sender: address
    receiver: address
    amount: uint256

struct Stake:
    caller: address
    account: address
    amount: uint256

struct Unstake:
    account: address
    amount: uint256

last_transfer: public(Transfer)
last_stake: public(Stake)
last_unstake: public(Unstake)
instant_withdrawal: public(HashMap[address, bool])

@external
def on_transfer(_caller: address, _from: address, _to: address, _value: uint256):
    self.last_transfer = Transfer(caller=_caller, sender=_from, receiver=_to, amount=_value)

@external
def on_stake(_caller: address, _account: address, _value: uint256):
    self.last_stake = Stake(caller=_caller, account=_account, amount=_value)

@external
def on_unstake(_account: address, _value: uint256):
    self.last_unstake = Unstake(account=_account, amount=_value)

@external
def set_instant_withdrawal(_account: address, _instant: bool):
    self.instant_withdrawal[_account] = _instant
