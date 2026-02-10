# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun

event SetWhitelist:
    vest: indexed(address)
    operator: address
    flag: bool

whitelist: public(HashMap[address, HashMap[address, bool]]) # vest => operator => flag

YCHAD: public(constant(address)) = 0xFEB4acf3df3cDEA7399794D0869ef76A6EfAff52

@external
def set_whitelist(_vest: address, _operator: address, _flag: bool):
    assert msg.sender == YCHAD
    self.whitelist[_vest][_operator] = _flag
    log SetWhitelist(vest=_vest, operator=_operator, flag=_flag)
