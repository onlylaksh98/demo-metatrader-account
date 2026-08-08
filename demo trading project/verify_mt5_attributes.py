"""Verification script to test MT5 API with correct TerminalInfo attributes."""
import os
from dotenv import load_dotenv
from loguru import logger

# Setup logging
logger.remove()  # Remove default handler
logger.add("logs/verify_mt5.log", rotation="100 KB")
logger.add(lambda msg: print(msg), colorize=True)

load_dotenv()

# Import MT5 connection after env is loaded
from mt5.connection import MT5Connection

def verify_mt5_functions():
    """Verify all 5 key MT5 functions work correctly."""
    logger.info("=" * 60)
    logger.info("MT5 VERIFICATION SCRIPT - Testing 5 Key Functions")
    logger.info("=" * 60)

    connection = MT5Connection()

    # Test 1: initialize() via connect()
    logger.info("\n[TEST 1] Testing initialize() via connect()")
    try:
        result = connection.connect()
        if result:
            logger.info("✓ initialize() PASSED - Connection successful")
        else:
            logger.error("✗ initialize() FAILED - Connection unsuccessful")
            return False
    except Exception as e:
        logger.error(f"✗ initialize() EXCEPTION: {e}")
        return False

    # Test 2: login() verification (called within initialize)
    logger.info("\n[TEST 2] Testing login() - Verified in connect()")
    try:
        import MetaTrader5 as mt5
        account = mt5.account_info()
        if account:
            logger.info(f"✓ login() PASSED - Account {account.login} logged in")
        else:
            logger.error("✗ login() FAILED - Could not get account info")
            return False
    except Exception as e:
        logger.error(f"✗ login() EXCEPTION: {e}")
        return False

    # Test 3: terminal_info() with safe attribute access using _asdict()
    logger.info("\n[TEST 3] Testing terminal_info() - Safe attribute access")
    try:
        import MetaTrader5 as mt5
        term_info = mt5.terminal_info()
        if term_info:
            logger.info("✓ terminal_info() PASSED")
            
            # Use _asdict() to safely access only existing attributes
            term_data = term_info._asdict() if hasattr(term_info, '_asdict') else {}
            
            connected = term_data.get('connected', False)
            trade_allowed = term_data.get('trade_allowed', False)
            tradeapi_disabled = term_data.get('tradeapi_disabled', False)
            
            logger.info(f"  - connected: {connected} (bool)")
            logger.info(f"  - trade_allowed: {trade_allowed} (bool)")
            logger.info(f"  - tradeapi_disabled: {tradeapi_disabled} (bool)")
            logger.info("  ✓ Using safe _asdict() method instead of attribute access")
            logger.info("  ✓ NO access to non-existent attributes")
        else:
            logger.error("✗ terminal_info() FAILED - Returned None")
            return False
    except Exception as e:
        logger.error(f"✗ terminal_info() EXCEPTION: {e}")
        return False

    # Test 4: account_info()
    logger.info("\n[TEST 4] Testing account_info()")
    try:
        import MetaTrader5 as mt5
        account = mt5.account_info()
        if account:
            logger.info("✓ account_info() PASSED")
            logger.info(f"  - login: {account.login}")
            logger.info(f"  - name: {account.name}")
            logger.info(f"  - balance: {account.balance}")
            logger.info(f"  - equity: {account.equity}")
            logger.info(f"  - trade_allowed: {account.trade_allowed}")
        else:
            logger.error("✗ account_info() FAILED - Returned None")
            return False
    except Exception as e:
        logger.error(f"✗ account_info() EXCEPTION: {e}")
        return False

    # Test 5: symbols_total()
    logger.info("\n[TEST 5] Testing symbols_total()")
    try:
        import MetaTrader5 as mt5
        total = mt5.symbols_total()
        if total is not None and total > 0:
            logger.info(f"✓ symbols_total() PASSED - Total symbols: {total}")
        else:
            logger.error(f"✗ symbols_total() FAILED - Returned: {total}")
            return False
    except Exception as e:
        logger.error(f"✗ symbols_total() EXCEPTION: {e}")
        return False

    logger.info("\n" + "=" * 60)
    logger.info("✓ ALL VERIFICATION TESTS PASSED")
    logger.info("=" * 60)
    logger.info("\nKey Fixes Applied:")
    logger.info("  1. Removed terminal_info.connectionstatus access (non-existent)")
    logger.info("  2. Removed terminal_info.tradeapi access (non-existent)")
    logger.info("  3. Implemented safe _asdict() method for attribute access")
    logger.info("  4. Use data.get(key) pattern instead of direct attribute access")
    logger.info("  5. Valid TerminalInfo attributes from actual object:")
    logger.info("     - connected (bool)")
    logger.info("     - trade_allowed (bool)")
    logger.info("     - tradeapi_disabled (bool)")
    logger.info("     - dlls_allowed (bool)")
    logger.info("     - community_account (bool)")
    logger.info("     - build (int)")
    logger.info("     - path (str)")
    logger.info("     - And more (see actual object in logs)")
    logger.info("=" * 60)

    # Cleanup
    connection.disconnect()
    return True

if __name__ == "__main__":
    os.makedirs("logs", exist_ok=True)
    try:
        success = verify_mt5_functions()
        exit(0 if success else 1)
    except Exception as e:
        logger.error(f"VERIFICATION SCRIPT FAILED: {e}")
        exit(1)
