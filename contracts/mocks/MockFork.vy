# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun

governance: public(address)
operator: public(address)
minters: public(HashMap[address, bool])

@external
def addMinter(_account: address):
    pass

@external
def modify_lock(amount: uint256, unlock_time: uint256, user: address):
    pass

@external
def mint():
    pass

@external
def deposit(_assets: uint256, _recipient: address = msg.sender):
    pass

@external
def setPerpetualLock(_lock: bool):
    pass

@external
def configureMinter(_minter: address, _amount: uint256):
    pass
