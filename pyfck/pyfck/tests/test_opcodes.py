"""
Tests for the individual opcodes

Separated from general tests of bfParser, so those can be independent of opcodes

Marius Lambacher, 2017
"""
import random
from unittest import TestCase, skip
from unittest.mock import patch

import itertools

from ..bfalParser import Parser
from ..bfInterpreter import Interpreter
from . import dummyOpcodes
from . import dummyMemoryLayout
import numpy as np
from io import StringIO
import sys
import re


class TestOpcodes(TestCase):
  def setUp(self):
    self.memorySize = 30000

    self.parser = Parser()
    print(self.parser.CELLS)
    self.interpreter = Interpreter(memorySize=self.memorySize)

  def loadBfal(self, cmds):
    """Compile and load code into self.interpreter"""
    bf = self.parser.compile(cmds)
    self.interpreter.load(bf)

  def runBfal(self, cmds, memory=None):
    """Runs given code in self.interpreter. If memory is given, it is copied into the interpreter.memory"""
    self.loadBfal(cmds)
    if memory is None:
      self.interpreter.run()

    else:
      self.interpreter.init()
      self.interpreter.memory = memory.copy()
      self.noInitRun()



  def noInitRun(self):
    """Run the interpreter without initialisation"""
    self.interpreter.running = True
    while self.interpreter.running:
      self.interpreter._step()

  def tracing(self, width=20):
    """Start tracing"""
    self.interpreter.tracing = True
    self.interpreter.traceWidth = width

  def printTrace(self):
    """Print the trace"""
    print('   ' +  '  '.join(map(lambda x: '{:>3}'.format(x), self.parser.CELLS[:self.interpreter.traceWidth])))
    print(self.interpreter.trace)

  def debugBfal(self, cmds, nSteps=100, memory=None):
    """Debug nSteps steps of cmds, useful when caught in endless loops"""

    self.tracing()
    self.interpreter.debugging=True

    self.interpreter.load(self.parser.compile(cmds))
    self.interpreter.init()
    if memory is not None:self.interpreter.memory = memory

    self.interpreter.running = True
    for i in range(nSteps): self.interpreter.step()


  def getCell(self, cell, memory=None):
    """Syntactic sugar for getting a cell by its name; if memory is None, use self.interpreter.memory"""

    if memory is None: memory = self.interpreter.memory
    return memory[self.parser.CELLS.index(cell)]

  def setCell(self, cell, value, memory=None):
    """Syntactic sugar for setting a cell by its name; if memory is None, use self.interpreter.memory"""

    if memory is None: memory = self.interpreter.memory
    memory[self.parser.CELLS.index(cell)] = value


  def atTestRegisters(self, nDim=1, nRegs=4, resetCount=False):
    """Decorator, call test for each combination of ndim (out of nRegs) testRegisters, passed to it via 'reg' or 'reg[0-(nDim-1)]'"""

    def testDecorator(test):
      def testDecorated(**kwargs):
        testRegisters = ['R0', 'R1', 'R7', 'R3', 'R2', 'R5', 'R4', 'R6']
        testRegisters = testRegisters[:nRegs]

        combinations = itertools.product(testRegisters, repeat=nDim)
        argNames = ['reg{}'.format(i) for i in range(nDim)]
        for c in combinations:
          if resetCount:
            key = 'TestCount_for_{}'.format(test.__name__)
            if key in self.__dict__: self.__dict__[key] = 0

          if nDim == 1: regArgs = {'reg': c[0]}
          else: regArgs = dict(zip(argNames, c))
          #print(test.__name__, regArgs)
          test(**regArgs, **kwargs)

      testDecorated.__name__ = test.__name__
      return testDecorated
    return testDecorator


  def withTestValues(self, *expr):
    """Decorator, run test with a test value, passed to test via 'val' or 'val[0-(ndim-1)]'
    expr: expression the values are generated from, called with a running count, passed via 'val'
            if multiple, a value is generated for each expression in the iterable"""

    def testDecorator(test):
      def testDecorated(**kwargs):
        key = 'TestCount_for_{}'.format(test.__name__)
        if not key in self.__dict__: self.__dict__[key] = 0

        valArgs = {}
        if len(expr) > 1:
          for i, e in enumerate(expr):
            valArgs['val{}'.format(i)] = e(self.__dict__[key])

        else:
          valArgs['val'] = expr[0](self.__dict__[key])

        test(**valArgs, **kwargs)
        self.__dict__[key] += 1

      testDecorated.__name__ = test.__name__
      return testDecorated
    return testDecorator


  def runNTimes(self, n):
    """Decorator, run test n times (e.g. for use in combination with @self.withTestValues)"""

    def testDecorator(test):
      def testDecorated(**kwargs):
        for i in range(n):
          test(**kwargs)

      testDecorated.__name__ = test.__name__
      return testDecorated
    return testDecorator



  def skipEqualRegisters(self, *positions):
    """Skip test if registers are equal
    positions (if given) are register argument indices; if they are equal, they are skipped
    if not given, the test is skipped if all given registers are equal"""

    def testDecorator(test):
      def testDecorated(**kwargs):
        regs = []
        if len(positions):
          for p in positions: regs.append(kwargs['reg{}'.format(p)])

        else:
          for i in range(3):    # maximum number of arguments
            name = 'reg{}'.format(i)
            if name in kwargs: regs.append(kwargs[name])
            else: break

        if regs.count(regs[0]) != len(regs): test(**kwargs)

      testDecorated.__name__ = test.__name__
      return testDecorated
    return testDecorator



  def zerosTest(self, test, rc=0, **kwargs):
    """test with memory set to 0s; the condition register can be set independently."""

    key = 'TestCount_for_{}'.format(test.__name__)
    self.__dict__[key] = 0

    memory = np.zeros(self.memorySize, dtype='u1')
    self.setCell('RC', rc, memory)

    test(memory=memory, **kwargs)

  def nonzerosTest(self, test, rc=0, **kwargs):
    """test with registers containing nonzero values; the condition register can be set independently"""

    key = 'TestCount_for_{}'.format(test.__name__)
    self.__dict__[key] = 0

    memory = np.zeros(self.memorySize, dtype='u1')
    self.setCell('RC', rc, memory)

    for reg in self.parser.REGISTERS:
      i = self.parser.CELLS.index(reg)
      val = i*13+5
      if i % 2: val = ~val
      memory[i] = val

    test(memory=memory, **kwargs)


  def initMemory(self, memory):
    """Initialise memory"""

    for reg, val in self.parser.CONSTANTS:
      self.setCell(reg, val, memory)

  def createStack(self, memory, vals):
    """Add stack to memory; values in order as given in vals"""

    index = self.parser.CELLS.index('STACK') + 2
    for i, val in enumerate(vals):
      memory[index+2*i] = 1
      memory[index+2*i+1] = val


  def generateMemoryChange(self, memory, reg, val=None, expr=None):
    """Change register either to val or to expr(old register value)"""

    if ((val is not None) and (expr is not None)) or ((val is None) and (expr is None)):
      raise NameError('Either value or expr should be given, not both nor neither!')

    if val is not None: self.setCell(reg, val, memory)
    else: self.setCell(reg, expr(self.getCell(reg, memory)), memory)



  def assertRegisterEqual(self, memory, reg, val=None, expr=None):
    """Assert two things:
        - reg is equal to val if given, or to expr(previous register value) if given
        - rest of memory is unchanged
    """

    m = memory.copy()
    self.initMemory(m)
    self.generateMemoryChange(m, reg, val, expr)
    np.testing.assert_array_equal(self.interpreter.memory, m)

  def assertRegisterNotEqual(self, memory, reg, val=None, expr=None):
    """Assert two things:
        - reg is not equal to val if given, or to expr(previous register value) if given
        - rest of memory is unchanged
    """

    cm = memory.copy()
    self.initMemory(cm)
    self.generateMemoryChange(cm, reg, val, expr)

    im = self.interpreter.memory
    i = self.parser.CELLS.index(reg)
    np.testing.assert_array_equal(im[:i], cm[:i])
    np.testing.assert_array_equal(im[i+1:], cm[i+1:])
    self.assertNotEqual(im[i], cm[i])



  def test_opcodes_allImplemented(self):
    keys = self.__class__.__dict__.keys()
    for opc in self.parser.OPCODES:
      for t in self.parser.OPCODE_TYPES[opc][1]:
        if t == '': name = opc.name
        else: name = '{}_{}'.format(opc.name, t.upper())

        r = re.compile('test_opcodes_{}$'.format(name))
        for k in keys:
          if r.match(k): break

        else: self.fail('Test for {} not implemented'.format(name))


  def test_opcodes_initConstants(self):
    def initConstants(memory):
      self.runBfal('', memory)

      m = memory.copy()
      self.initMemory(m)

      np.testing.assert_array_equal(self.interpreter.memory, m)

    self.zerosTest(initConstants)
    self.nonzerosTest(initConstants)



  def test_opcodes_SET_RV(self):
    @self.atTestRegisters()
    @self.withTestValues(lambda i: i**2)
    def SET_RV(memory, reg, val):
      self.runBfal('SET {} {}'.format(reg, val), memory)
      self.assertRegisterEqual(memory, reg, val=val)

    self.zerosTest(SET_RV)
    self.nonzerosTest(SET_RV)

  def test_opcodes_SET_RR(self):
    @self.atTestRegisters(nDim=2)
    @self.withTestValues(lambda i: i**2)
    def SET_RR(memory, reg0, reg1, val):
      m = memory.copy()
      self.setCell(reg1, val, m)
      self.runBfal('SET {} {}'.format(reg0, reg1), m)
      self.assertRegisterEqual(m, reg0, val=val)

    self.zerosTest(SET_RR)
    self.nonzerosTest(SET_RR)


  def test_opcodes_STZ_R(self):
    @self.atTestRegisters()
    def STZ_R(memory, reg):
      self.runBfal('STZ {}'.format(reg), memory)
      self.assertRegisterEqual(memory, reg, val=0)

    self.nonzerosTest(STZ_R)

  def test_opcodes_PUSH_V(self):
    @self.runNTimes(7)
    @self.withTestValues(lambda i: ([0,], [0, 10], [10,], [10, 0], [10, 20], [10, 20, 0], [10, 20, 0, 30])[i])
    def PUSH_V(memory, val):
      cmds = '\n'.join('PUSH {}'.format(v) for v in val)
      self.runBfal(cmds, memory)

      m = memory.copy()
      self.initMemory(m)
      self.createStack(m, val)
      np.testing.assert_array_equal(self.interpreter.memory, m)

    self.zerosTest(PUSH_V)
    self.nonzerosTest(PUSH_V)

  def test_opcodes_PUSH_R(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(7)
    @self.withTestValues(lambda i: ([0,], [0, 10], [10,], [10, 0], [10, 20], [10, 20, 0], [10, 20, 0, 30])[i])
    def PUSH_R(memory, reg, val):
      cmds = '\n'.join('SET {} {}\nPUSH {}'.format(reg, v, reg) for v in val)
      self.runBfal(cmds, memory)
      m = memory.copy()
      self.initMemory(m)
      self.createStack(m, val)
      self.setCell(reg, val[-1], m)
      np.testing.assert_array_equal(self.interpreter.memory, m)

    self.zerosTest(PUSH_R)
    self.nonzerosTest(PUSH_R)
    
  def test_opcodes_POP_R(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(7)
    @self.withTestValues(lambda i: ([0,], [0, 10], [10,], [10, 0], [10, 20], [10, 20, 0], [10, 20, 0, 30])[i])
    def POP_R(memory, reg, val):
      m = memory.copy()
      self.createStack(m, val)

      for i, v in enumerate(reversed(val)):
        cmds = (i+1) * 'POP {}\n'.format(reg)
        self.runBfal(cmds, m)
        mChanged = memory.copy()
        self.createStack(mChanged, val[:-(i+1)])
        self.assertRegisterEqual(mChanged, reg, v)

    self.zerosTest(POP_R)
    self.nonzerosTest(POP_R)


  def test_opcodes_INC_R(self):
    @self.atTestRegisters()
    def INC_R(memory, reg):
      self.runBfal('INC {}'.format(reg), memory)
      self.assertRegisterEqual(memory, reg, expr=lambda v: v + 1)

    self.zerosTest(INC_R)
    self.nonzerosTest(INC_R)


  def test_opcodes_INC_RV(self):
    @self.atTestRegisters()
    @self.withTestValues(lambda i: i**2)
    def INC_RV(memory, reg, val):
      self.runBfal('INC {} {}'.format(reg, val), memory)
      self.assertRegisterEqual(memory, reg, expr=lambda v: v + val)

    self.zerosTest(INC_RV)
    self.nonzerosTest(INC_RV)

  def test_opcodes_INC_RR(self):
    @self.atTestRegisters(nDim=2)
    @self.withTestValues(lambda i: i**2)
    @self.skipEqualRegisters()
    def INC_RR(memory, reg0, reg1, val):
      m = memory.copy()
      self.setCell(reg1, val, m)
      self.runBfal('INC {} {}'.format(reg0, reg1), m)
      self.assertRegisterEqual(m, reg0, expr=lambda v: v+val)

    self.zerosTest(INC_RR)
    self.nonzerosTest(INC_RR)

  def test_opcodes_DEC_R(self):
    @self.atTestRegisters()
    def DEC_R(memory, reg):
      self.runBfal('DEC {}'.format(reg), memory)
      self.assertRegisterEqual(memory, reg, expr=lambda v: v-1)

    self.zerosTest(DEC_R)
    self.nonzerosTest(DEC_R)


  def test_opcodes_DEC_RV(self):
    @self.atTestRegisters()
    @self.withTestValues(lambda i: i**2)
    def DEC_RV(memory, reg, val):
      self.runBfal('DEC {} {}'.format(reg, val), memory)
      self.assertRegisterEqual(memory, reg, expr=lambda v: v-val)

    self.zerosTest(DEC_RV)
    self.nonzerosTest(DEC_RV)

  def test_opcodes_DEC_RR(self):
    @self.atTestRegisters(nDim=2)
    @self.withTestValues(lambda i: i**2)
    @self.skipEqualRegisters()
    def DEC_RR(memory, reg0, reg1, val):
      m = memory.copy()
      self.setCell(reg1, val, m)
      self.runBfal('DEC {} {}'.format(reg0, reg1), m)
      self.assertRegisterEqual(m, reg0, expr=lambda v: v-val)

    self.zerosTest(DEC_RR)
    self.nonzerosTest(DEC_RR)
    
  def test_opcodes_ADD_RVV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i**2, lambda j: j**2+2)
    def ADD_RVV(memory, reg, val0, val1):
      self.runBfal('ADD {} {} {}'.format(reg, val0, val1), memory)
      self.assertRegisterEqual(memory, reg, val=val0+val1)

    self.zerosTest(ADD_RVV)
    self.zerosTest(ADD_RVV, rc=1)
    self.nonzerosTest(ADD_RVV)

  def test_opcodes_ADD_RRV(self):
    @self.atTestRegisters(nDim=2)
    @self.withTestValues(lambda i: i**2, lambda j: j**2+2)
    def ADD_RRV(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg1, val0, m)
      self.runBfal('ADD {} {} {}'.format(reg0, reg1, val1), m)
      self.assertRegisterEqual(m, reg0, val=val0+val1)

    self.zerosTest(ADD_RRV)
    self.nonzerosTest(ADD_RRV)

  def test_opcodes_ADD_RRR(self):
    @self.atTestRegisters(nDim=3, nRegs=3)
    @self.withTestValues(lambda i: i**2, lambda j: j**2+2)
    @self.skipEqualRegisters(0, 2)
    def ADD_RRR(memory, reg0, reg1, reg2, val0, val1):
      if reg1 == reg2: val1 = val0

      m = memory.copy()
      self.setCell(reg1, val0, m)
      self.setCell(reg2, val1, m)
      self.runBfal('ADD {} {} {}'.format(reg0, reg1, reg2), m)
      self.assertRegisterEqual(m, reg0, val=val0+val1)

    self.zerosTest(ADD_RRR)
    self.nonzerosTest(ADD_RRR)
  
  def test_opcodes_SUB_RVV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i**2, lambda j: j**2+2)
    def SUB_RVV(memory, reg, val0, val1):
      self.runBfal('SUB {} {} {}'.format(reg, val0, val1), memory)
      self.assertRegisterEqual(memory, reg, val=val0-val1)

    self.zerosTest(SUB_RVV)
    self.zerosTest(SUB_RVV, rc=1)
    self.nonzerosTest(SUB_RVV)

  def test_opcodes_SUB_RRV(self):
    @self.atTestRegisters(nDim=2)
    @self.withTestValues(lambda i: i**2, lambda j: j**2+2)
    def SUB_RRV(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg1, val0, m)
      self.runBfal('SUB {} {} {}'.format(reg0, reg1, val1), m)
      self.assertRegisterEqual(m, reg0, val=val0-val1)

    self.zerosTest(SUB_RRV)
    self.nonzerosTest(SUB_RRV)


  def test_opcodes_SUB_RRR(self):
    @self.atTestRegisters(nDim=3, nRegs=3)
    @self.withTestValues(lambda i: i**2, lambda j: j**2+2)
    @self.skipEqualRegisters(0, 2)
    def SUB_RRR(memory, reg0, reg1, reg2, val0, val1):
      if reg1 == reg2: val1 = val0
      m = memory.copy()
      self.setCell(reg1, val0, m)
      self.setCell(reg2, val1, m)
      self.runBfal('SUB {} {} {}'.format(reg0, reg1, reg2), m)
      self.assertRegisterEqual(m, reg0, val=val0-val1)

    self.zerosTest(SUB_RRR)
    self.nonzerosTest(SUB_RRR)
   
  def test_opcodes_MUL_RVV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i**2, lambda j: j**2+2)
    def MUL_RVV(memory, reg, val0, val1):
      self.runBfal('MUL {} {} {}'.format(reg, val0, val1), memory)
      self.assertRegisterEqual(memory, reg, val=val0*val1)

    self.zerosTest(MUL_RVV)
    self.zerosTest(MUL_RVV, rc=1)
    self.nonzerosTest(MUL_RVV) 
    
  def test_opcodes_MUL_RRV(self):
    @self.atTestRegisters(nDim=2)
    @self.withTestValues(lambda i: i, lambda j: j*2)
    def MUL_RRV(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg1, val0, m)
      self.runBfal('MUL {} {} {}'.format(reg0, reg1, val1), m)
      self.assertRegisterEqual(m, reg0, val=val0*val1)

    self.zerosTest(MUL_RRV)
    self.nonzerosTest(MUL_RRV)


  def test_opcodes_MUL_RRR(self):
    @self.atTestRegisters(nDim=3, nRegs=3)
    @self.withTestValues(lambda i: (i-1), lambda j: (j-1)*2)
    @self.skipEqualRegisters(0, 2)
    def MUL_RRR(memory, reg0, reg1, reg2, val0, val1):
      if reg1 == reg2: val1 = val0
      m = memory.copy()
      self.setCell(reg1, val0, m)
      self.setCell(reg2, val1, m)
      self.runBfal('MUL {} {} {}'.format(reg0, reg1, reg2), m)
      self.assertRegisterEqual(m, reg0, val=val0*val1)

    self.zerosTest(MUL_RRR)
    self.nonzerosTest(MUL_RRR)
    
  def test_opcodes_DIV_RVV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: 10*i if i%2 else 0, lambda j: 10*(j//2))
    def DIV_RVV(memory, reg, val0, val1):
      self.runBfal('DIV {} {} {}'.format(reg, val0, val1), memory)
      self.assertRegisterEqual(memory, reg, val= val0//val1 if val1 else 0)

    self.zerosTest(DIV_RVV)
    self.zerosTest(DIV_RVV, rc=1)
    self.nonzerosTest(DIV_RVV) 
    
  def test_opcodes_DIV_RRV(self):
    @self.atTestRegisters(nDim=2, resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: 10*i if i%2 else 0, lambda j: 10*(j//2))
    def DIV_RRV(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg1, val0, m)
      self.runBfal('DIV {} {} {}'.format(reg0, reg1, val1), m)
      self.assertRegisterEqual(m, reg0, val= val0//val1 if val1 else 0)

    self.zerosTest(DIV_RRV)
    self.nonzerosTest(DIV_RRV)


  def test_opcodes_DIV_RRR(self):
    @self.atTestRegisters(nDim=3, nRegs=3, resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: 10*i if i%2 else 0, lambda j: 10*(j//2))
    @self.skipEqualRegisters(0, 2)
    def DIV_RRR(memory, reg0, reg1, reg2, val0, val1):
      if reg1 == reg2: val1 = val0
      m = memory.copy()
      self.setCell(reg1, val0, m)
      self.setCell(reg2, val1, m)
      self.runBfal('DIV {} {} {}'.format(reg0, reg1, reg2), m)
      self.assertRegisterEqual(m, reg0, val= val0//val1 if val1 else 0)

    self.zerosTest(DIV_RRR)
    self.nonzerosTest(DIV_RRR)


  def test_opcodes_TRUE(self):
    @self.runNTimes(2)
    @self.withTestValues(lambda i: i)
    def TRUE(memory, val):
      m = memory.copy()
      self.setCell('RC', val, m)
      self.runBfal('TRUE', m)
      self.assertRegisterEqual(memory, 'RC', val=1)

    self.zerosTest(TRUE)
    self.nonzerosTest(TRUE)
    
  def test_opcodes_FALSE(self):
    @self.runNTimes(2)
    @self.withTestValues(lambda i: i)
    def FALSE(memory, val):
      m = memory.copy()
      self.setCell('RC', val, m)
      self.runBfal('FALSE', m)
      self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(FALSE)
    self.nonzerosTest(FALSE)

  def test_opcodes_NOT(self):
    @self.runNTimes(2)
    @self.withTestValues(lambda i: i)
    def NOT(memory, val):
      m = memory.copy()
      self.setCell('RC', val, m)
      self.runBfal('NOT', m)
      if val: self.assertRegisterEqual(memory, 'RC', val=0)
      else: self.assertRegisterEqual(memory, 'RC', val=1)

    self.zerosTest(NOT)
    self.nonzerosTest(NOT)

  def test_opcodes_ZERO_V(self):
    @self.runNTimes(2)
    @self.withTestValues(lambda i: 42*(i%2))
    def ZERO_V(memory, val):
      self.runBfal('ZR {}'.format(val), memory)
      if val == 0: self.assertRegisterEqual(memory, 'RC', val=1)
      else: self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(ZERO_V)
    self.zerosTest(ZERO_V, rc=1)
    self.nonzerosTest(ZERO_V)

  def test_opcodes_ZERO_R(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(2)
    @self.withTestValues(lambda i: 42*(i%2))
    def ZERO_R(memory, reg, val):
      m = memory.copy()
      self.setCell(reg, val, m)

      self.runBfal('ZR {}'.format(reg), m)
      self.printTrace()
      if val == 0: self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(ZERO_R)
    self.zerosTest(ZERO_R, rc=1)
    self.nonzerosTest(ZERO_R)

  def test_opcodes_NOT_ZERO_V(self):
    @self.runNTimes(2)
    @self.withTestValues(lambda i: 42*(i%2))
    def NOT_ZERO_V(memory, val):
      self.runBfal('NZ {}'.format(val), memory)
      if val != 0: self.assertRegisterEqual(memory, 'RC', val=1)
      else: self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(NOT_ZERO_V)
    self.zerosTest(NOT_ZERO_V, rc=1)
    self.nonzerosTest(NOT_ZERO_V)

  def test_opcodes_NOT_ZERO_R(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(2)
    @self.withTestValues(lambda i: 42*(i%2))
    def NOT_ZERO_R(memory, reg, val):
      m = memory.copy()
      self.setCell(reg, val, m)
      self.runBfal('NZ {}'.format(reg), m)
      if val != 0: self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(NOT_ZERO_R)
    self.zerosTest(NOT_ZERO_R, rc=1)
    self.nonzerosTest(NOT_ZERO_R)

  def test_opcodes_EQUAL_VV(self):
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def EQUAL_VV(memory, val0, val1):
      self.runBfal('EQ {} {}'.format(val0, val1), memory)
      if val0 == val1: self.assertRegisterEqual(memory, 'RC', val=1)
      else: self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(EQUAL_VV)
    self.zerosTest(EQUAL_VV, rc=1)
    self.nonzerosTest(EQUAL_VV)

  def test_opcodes_EQUAL_RV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def EQUAL_RV(memory, reg, val0, val1):
      m = memory.copy()
      self.setCell(reg, val0, m)
      self.runBfal('EQ {} {}'.format(reg, val1), m)
      if val0 == val1: self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(EQUAL_RV)
    self.zerosTest(EQUAL_RV, rc=1)
    self.nonzerosTest(EQUAL_RV)

  def test_opcodes_EQUAL_RR(self):
    @self.atTestRegisters(nDim=2, nRegs=3, resetCount=True)
    @self.runNTimes(3)
    @self.withTestValues(lambda i: i+1, lambda j: ((j+1)**2)//2)
    def EQUAL_RR(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg0, val0, m)
      self.setCell(reg1, val1, m)
      self.runBfal('EQ {} {}'.format(reg0, reg1), m)
      if (reg0 == reg1) or (val0 == val1): self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(EQUAL_RR)
    self.zerosTest(EQUAL_RR, rc=1)
    self.nonzerosTest(EQUAL_RR)

  def test_opcodes_NOT_EQUAL_VV(self):
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def NOT_EQUAL_VV(memory, val0, val1):
      self.runBfal('NE {} {}'.format(val0, val1), memory)
      if val0 != val1: self.assertRegisterEqual(memory, 'RC', val=1)
      else: self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(NOT_EQUAL_VV)
    self.zerosTest(NOT_EQUAL_VV, rc=1)
    self.nonzerosTest(NOT_EQUAL_VV)

  def test_opcodes_NOT_EQUAL_RV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def NOT_EQUAL_RV(memory, reg, val0, val1):
      m = memory.copy()
      self.setCell(reg, val0, m)
      self.runBfal('NE {} {}'.format(reg, val1), m)
      if val0 != val1: self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(NOT_EQUAL_RV)
    self.zerosTest(NOT_EQUAL_RV, rc=1)
    self.nonzerosTest(NOT_EQUAL_RV)

  def test_opcodes_NOT_EQUAL_RR(self):
    @self.atTestRegisters(nDim=2, nRegs=3, resetCount=True)
    @self.runNTimes(3)
    @self.withTestValues(lambda i: i+1, lambda j: ((j+1)**2)//2)
    def NOT_EQUAL_RR(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg0, val0, m)
      self.setCell(reg1, val1, m)
      self.runBfal('NE {} {}'.format(reg0, reg1), m)
      if (reg0 != reg1) and (val0 != val1): self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(NOT_EQUAL_RR)
    self.zerosTest(NOT_EQUAL_RR, rc=1)
    self.nonzerosTest(NOT_EQUAL_RR)


  def test_opcodes_GREATER_VV(self):
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def GREATER_VV(memory, val0, val1):
      self.runBfal('GT {} {}'.format(val0, val1), memory)
      if val0 > val1: self.assertRegisterEqual(memory, 'RC', val=1)
      else: self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(GREATER_VV)
    self.zerosTest(GREATER_VV, rc=1)
    self.nonzerosTest(GREATER_VV)

  def test_opcodes_GREATER_RV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def GREATER_RV(memory, reg, val0, val1):
      m = memory.copy()
      self.setCell(reg, val0, m)
      self.runBfal('GT {} {}'.format(reg, val1), m)
      if val0 > val1: self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(GREATER_RV)
    self.zerosTest(GREATER_RV, rc=1)
    self.nonzerosTest(GREATER_RV)

  def test_opcodes_GREATER_RR(self):
    @self.atTestRegisters(nDim=2, nRegs=3, resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i+1, lambda j: ((j+1)**2)//2)
    def GREATER_RR(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg0, val0, m)
      self.setCell(reg1, val1, m)
      self.runBfal('GT {} {}'.format(reg0, reg1), m)
      if (reg0 != reg1) and (val0 > val1): self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(GREATER_RR)
    self.zerosTest(GREATER_RR, rc=1)
    self.nonzerosTest(GREATER_RR)
  
  def test_opcodes_GREATER_EQUAL_VV(self):
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def GREATER_VV(memory, val0, val1):
      self.runBfal('GE {} {}'.format(val0, val1), memory)
      if val0 >= val1: self.assertRegisterEqual(memory, 'RC', val=1)
      else: self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(GREATER_VV)
    self.zerosTest(GREATER_VV, rc=1)
    self.nonzerosTest(GREATER_VV)

  def test_opcodes_GREATER_EQUAL_RV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def GREATER_EQUAL_RV(memory, reg, val0, val1):
      m = memory.copy()
      self.setCell(reg, val0, m)
      self.runBfal('GE {} {}'.format(reg, val1), m)
      if val0 >= val1: self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(GREATER_EQUAL_RV)
    self.zerosTest(GREATER_EQUAL_RV, rc=1)
    self.nonzerosTest(GREATER_EQUAL_RV)

  def test_opcodes_GREATER_EQUAL_RR(self):
    @self.atTestRegisters(nDim=2, nRegs=3, resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i+1, lambda j: ((j+1)**2)//2)
    def GREATER_EQUAL_RR(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg0, val0, m)
      self.setCell(reg1, val1, m)
      self.runBfal('GE {} {}'.format(reg0, reg1), m)
      if (reg0 == reg1) or (val0 >= val1): self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(GREATER_EQUAL_RR)
    self.zerosTest(GREATER_EQUAL_RR, rc=1)
    self.nonzerosTest(GREATER_EQUAL_RR)
  
  def test_opcodes_LESS_VV(self):
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def LESS_VV(memory, val0, val1):
      self.runBfal('LT {} {}'.format(val0, val1), memory)
      if val0 < val1: self.assertRegisterEqual(memory, 'RC', val=1)
      else: self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(LESS_VV)
    self.zerosTest(LESS_VV, rc=1)
    self.nonzerosTest(LESS_VV)

  def test_opcodes_LESS_RV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def LESS_RV(memory, reg, val0, val1):
      m = memory.copy()
      self.setCell(reg, val0, m)
      self.runBfal('LT {} {}'.format(reg, val1), m)
      if val0 < val1: self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(LESS_RV)
    self.zerosTest(LESS_RV, rc=1)
    self.nonzerosTest(LESS_RV)

  def test_opcodes_LESS_RR(self):
    @self.atTestRegisters(nDim=2, nRegs=3, resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i+1, lambda j: ((j+1)**2)//2)
    def LESS_RR(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg0, val0, m)
      self.setCell(reg1, val1, m)
      self.runBfal('LT {} {}'.format(reg0, reg1), m)
      if (reg0 != reg1) and (val0 < val1): self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(LESS_RR)
    self.zerosTest(LESS_RR, rc=1)
    self.nonzerosTest(LESS_RR)
    
  def test_opcodes_LESS_EQUAL_VV(self):
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def LESS_EQUAL_VV(memory, val0, val1):
      self.runBfal('LE {} {}'.format(val0, val1), memory)
      if val0 <= val1: self.assertRegisterEqual(memory, 'RC', val=1)
      else: self.assertRegisterEqual(memory, 'RC', val=0)

    self.zerosTest(LESS_EQUAL_VV)
    self.zerosTest(LESS_EQUAL_VV, rc=1)
    self.nonzerosTest(LESS_EQUAL_VV)

  def test_opcodes_LESS_EQUAL_RV(self):
    @self.atTestRegisters(resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i, lambda j: (j**2)//2)
    def LESS_EQUAL_RV(memory, reg, val0, val1):
      m = memory.copy()
      self.setCell(reg, val0, m)
      self.runBfal('LE {} {}'.format(reg, val1), m)
      if val0 <= val1: self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(LESS_EQUAL_RV)
    self.zerosTest(LESS_EQUAL_RV, rc=1)
    self.nonzerosTest(LESS_EQUAL_RV)

  def test_opcodes_LESS_EQUAL_RR(self):
    @self.atTestRegisters(nDim=2, nRegs=3, resetCount=True)
    @self.runNTimes(4)
    @self.withTestValues(lambda i: i+1, lambda j: ((j+1)**2)//2)
    def LESS_EQUAL_RR(memory, reg0, reg1, val0, val1):
      m = memory.copy()
      self.setCell(reg0, val0, m)
      self.setCell(reg1, val1, m)
      self.runBfal('LE {} {}'.format(reg0, reg1), m)
      if (reg0 == reg1) or (val0 <= val1): self.assertRegisterEqual(m, 'RC', val=1)
      else: self.assertRegisterEqual(m, 'RC', val=0)

    self.zerosTest(LESS_EQUAL_RR)
    self.zerosTest(LESS_EQUAL_RR, rc=1)
    self.nonzerosTest(LESS_EQUAL_RR)


  @patch('sys.stdin', new_callable=StringIO)
  def test_opcodes_INPUT_R(self, mock_stdin):
    @self.atTestRegisters()
    def INPUT_R(mock_stdin, memory, reg):
      string = 'B1ö'
      mock_stdin.write(string)

      for i, c in enumerate(string):
        mock_stdin.seek(i)
        self.runBfal('INP {}'.format(reg), memory)

        #m = memory.copy()
        #self.setCell(reg, ord(c), m)
        self.assertRegisterEqual(memory, reg, ord(c))
        #np.testing.assert_array_equal(self.interpreter.memory, m)

    self.zerosTest(INPUT_R, mock_stdin=mock_stdin)
    self.nonzerosTest(INPUT_R, mock_stdin=mock_stdin)


  @patch('sys.stdout', new_callable=StringIO)
  def test_opcodes_OUTPUT_R(self, mock_stdout):
    @self.atTestRegisters()
    def OUTPUT_R(mock_stdout, memory, reg):
      string = 'A0ä'
      mock_stdout.seek(0)

      for c in string:
        m = memory.copy()
        self.setCell(reg, ord(c), m)
        self.runBfal('OUT {}'.format(reg), m)

      self.assertEqual(mock_stdout.getvalue().strip(), string)

    self.zerosTest(OUTPUT_R, mock_stdout=mock_stdout)
    self.nonzerosTest(OUTPUT_R, mock_stdout=mock_stdout)



  def test_opcodes_LOOP(self):
    @self.atTestRegisters(nDim=2, nRegs=3)
    @self.skipEqualRegisters()
    @self.withTestValues(lambda i: i*3)
    def LOOP(memory, reg0, reg1, val):
      m = memory.copy()
      self.setCell(reg0, val, m)
      self.runBfal('STZ {1}\nNZ {0}\nLOOP\nDEC {0}\nINC {1}\nNZ {0}\nENDLOOP'.format(reg0, reg1), m)
      self.setCell(reg0, 0, m)
      self.assertRegisterEqual(m, reg1, val=val)

    self.zerosTest(LOOP)
    self.nonzerosTest(LOOP)


  def test_opcodes_IF(self):
    @self.atTestRegisters(nDim=2, nRegs=3)
    @self.skipEqualRegisters()
    @self.withTestValues(lambda i: i*3)
    def IF(memory, reg0, reg1, val):
      m = memory.copy()
      self.setCell(reg0, val, m)
      self.runBfal('SET {1} 42\nNZ {0}\nIF\nDEC {0}\nINC {1}\nENDIF'.format(reg0, reg1), m)
      self.setCell(reg1, 42, m)

      res = 42
      if val != 0:
        self.setCell(reg0, val-1, m)
        res = 43

      self.assertRegisterEqual(m, reg1, val=res)

    self.zerosTest(IF)
    self.nonzerosTest(IF)

  @skip('Already tested in test_opcodes_LOOP')
  def test_opcodes_END_LOOP(self): pass

  @skip('Already tested in test_opcodes_IF')
  def test_opcodes_END_IF(self): pass


  def test_opcodes_ALIAS_TV(self):
    self.parser.compile('ALIAS FOO 42')
    self.assertIn('FOO', self.parser.ALIASES)
    self.assertEqual(self.parser.ALIASES['FOO'], '42')

  def test_opcodes_ALIAS_TR(self):
    self.parser.compile('ALIAS FOO R0')
    self.assertIn('FOO', self.parser.ALIASES)
    self.assertEqual(self.parser.ALIASES['FOO'], 'R0')

  @patch('sys.stdout', new_callable=StringIO)
  def test_opcodes_PRINT_T(self, mock_stdout):
    def PRINT_T(mock_stdout, memory):
      mock_stdout.seek(0)

      string = 'C3ü'
      self.runBfal('PRT "{}"'.format(string), memory)
      self.assertEqual(mock_stdout.getvalue().strip(), string)
      m = memory.copy()
      self.initMemory(m)
      np.testing.assert_array_equal(self.interpreter.memory, m)


    self.zerosTest(PRINT_T, mock_stdout=mock_stdout)
    self.nonzerosTest(PRINT_T, mock_stdout=mock_stdout)

