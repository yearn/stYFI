# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Vesting Staker (1UP)
@author Yearn Finance
@license GNU AGPLv3
@notice Allows the vest recipient to stake their tokens into llYFI to earn rewards and 
        participate in governance while their tokens are vesting. Tokens can also be unstaked 
        and sent back to the vesting contract.
"""

from ethereum.ercs import IERC20
from ethereum.ercs import IERC4626

interface IVest:
    def recipient() -> address: view
    def token() -> address: view
    def call(_target: address, _data: Bytes[2048]): payable

interface IDepositor:
    def unstake(_amount: uint256): nonpayable

interface IWhitelist:
    def whitelist(_vest: address, _operator: address) -> bool: view

event Stake:
    amount: uint256

event Unstake:
    amount: uint256

event Claim:
    amount: uint256

event SetOperator:
    operator: indexed(address)
    flag: bool

event Call:
    operator: address
    target: address

vest: public(immutable(IVest))
recipient: public(immutable(address))
token: public(immutable(IERC20))
whitelist: public(immutable(IWhitelist))
operators: public(HashMap[address, bool])

DEPOSITOR: public(constant(address)) = 0x52Aa16860E0D42B6a7b6ecC15688472eb20135c9
SCALE: constant(uint256) = 69_420

@deploy
def __init__(_vest: address, _whitelist: address):
    """
    @notice Constructor
    @param _vest Address of the vest
    @param _whitelist Operator whitelist address
    """
    vest = IVest(_vest)
    recipient = staticcall vest.recipient()
    token = IERC20(staticcall vest.token())
    whitelist = IWhitelist(_whitelist)

    assert staticcall IERC4626(DEPOSITOR).asset() == token.address

@external
def stake(_amount: uint256):
    """
    @notice Stake into llYFI
    @param _amount Amount of YFI to stake
    """
    assert msg.sender == recipient
    scaled: uint256 = _amount * SCALE
    extcall vest.call(token.address, abi_encode(self, scaled, method_id=method_id("transfer(address,uint256)")))
    extcall token.approve(DEPOSITOR, scaled)
    extcall IERC4626(DEPOSITOR).mint(_amount, self)
    log Stake(amount=_amount)

@external
def unstake(_amount: uint256):
    """
    @notice Initiate unstake stream from llYFI
    @param _amount Amount of YFI to unstake
    """
    assert msg.sender == recipient
    extcall IDepositor(DEPOSITOR).unstake(_amount)
    log Unstake(amount=_amount)

@external
def claim(_amount: uint256 = max_value(uint256)):
    """
    @notice Claim from unstaking stream
    @param _amount Amount of YFI to claim
    """
    assert msg.sender == recipient
    amount: uint256 = _amount
    if _amount == max_value(uint256):
        amount = staticcall IERC4626(DEPOSITOR).maxRedeem(self)
    extcall IERC4626(DEPOSITOR).redeem(amount, vest.address, self)
    log Claim(amount=amount)

@external
def set_operator(_operator: address, _flag: bool):
    """
    @notice Add or remove an operator
    @param _operator Operator
    @param _flag True: operator, False: not operator
    """
    assert msg.sender == recipient
    assert _operator != empty(address)
    if _flag:
        assert staticcall whitelist.whitelist(vest.address, _operator)
    self.operators[_operator] = _flag
    log SetOperator(operator=_operator, flag=_flag)

@external
@payable
def call(_target: address, _data: Bytes[2048]):
    """
    @notice Call another contract through the operator
    @param _target The contract to call
    @param _data The calldata of the call
    """
    if msg.sender == recipient:
        assert _target not in [token.address, DEPOSITOR]
    else:
        assert self.operators[msg.sender]
    raw_call(_target, _data, value=msg.value)
    log Call(operator=msg.sender, target=_target)
