import unittest

from ch00_hello_agent import hello_agent
from ch01_structured_output import struct_out
from ch02_agent_loop import agent_loop

class TestAgent(unittest.TestCase):


    # hello agent，对agent有个出现认知；
    def test_hello_agent(self):
        hello_agent()
    # agent格式化输出
    def test_struct_out(self):
        struct_out()

    def test_agent_loop(self):
        agent_loop()



if __name__ == "__main__":
    unittest.main()
