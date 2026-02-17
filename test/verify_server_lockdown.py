
import sys
import os
import socket
import ctypes
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import find_available_port, acquire_single_instance_mutex

class TestServerSettings(unittest.TestCase):
    
    def test_find_available_port_free(self):
        """Test finding port when the requested one is free"""
        # We assume 5999 is free for this test
        port = find_available_port("127.0.0.1", 5999)
        self.assertEqual(port, 5999)

    def test_find_available_port_occupied(self):
        """Test finding port when the requested one is occupied"""
        # Occupy port 5998
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", 5998))
            # 5998 is now taken
            
            # Should find 5999 (assuming it's free)
            found_port = find_available_port("127.0.0.1", 5998)
            self.assertNotEqual(found_port, 5998)
            self.assertEqual(found_port, 5999)
        finally:
            sock.close()

    def test_mutex_behavior(self):
        """Test named mutex behavior"""
        if sys.platform != 'win32':
            print("Skipping mutex test on non-Windows platform")
            return

        # First acquisition
        handle1 = acquire_single_instance_mutex()
        self.assertIsNotNone(handle1)
        
        # Check that we have it
        kernel32 = ctypes.windll.kernel32
        # ERROR_ALREADY_EXISTS = 183
        # First call might have created it, or it might exist from a previous run if not cleaned up (but mutexes die with processes)
        # Actually, if we run this test, and no other instance is running, first call should NOT return 183.
        # But wait, acquire_single_instance_mutex returns None if it gets 183.
        
        # So handle1 should be a valid handle.
        
        # Second acquisition in SAME process
        # Windows CreateMutex returns handle + ERROR_ALREADY_EXISTS if it exists.
        # Our function returns None if GetLastError() == 183.
        
        # So calling it again *should* return None, because the mutex now exists (created by us).
        handle2 = acquire_single_instance_mutex()
        self.assertIsNone(handle2, "Second mutex acquisition should return None because it already exists")
        
        # Cleanup
        if handle1:
            kernel32.CloseHandle(handle1)

if __name__ == '__main__':
    unittest.main()
