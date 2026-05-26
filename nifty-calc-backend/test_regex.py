import re

def clean_symbol(symbol):
    return re.sub(r'\d{2}[A-Z]{3}\d{2}FUT$', '', symbol)

print(clean_symbol('BHEL28APR26FUT'))
print(clean_symbol('ANGELONE28APR26FUT'))
print(clean_symbol('HAL28APR26FUT'))
print(clean_symbol('M&M28APR26FUT'))
print(clean_symbol('M&MFIN28APR26FUT'))
print(clean_symbol('BAJAJ-AUTO28APR26FUT'))
