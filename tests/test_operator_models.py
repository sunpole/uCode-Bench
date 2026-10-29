import json
from pathlib import Path
import tempfile
import unittest

from ucode.operator_models import (SequenceSpec, SourceIndex, grouped_number,
                                   parse_number, estimate_space, JobApproval)


class OperatorModelTests(unittest.TestCase):
    def test_numeric_edit_format_preserves_zeroes_and_decimal(self):
        self.assertEqual(grouped_number('000000040000'), '000 000 040 000')
        self.assertEqual(grouped_number('1234567,25'), '1 234 567,25')
        self.assertEqual(parse_number('1\u202f234', integer=True), 1234)
        with self.assertRaises(ValueError): parse_number('1.2', integer=True)

    def test_sequences_and_last_number(self):
        self.assertEqual(SequenceSpec('500 000 000 000', 12000, 1).last, '500000011999')
        spec=SequenceSpec('000 000 100 000',5000,3)
        self.assertEqual(spec.first,'000000100000')
        self.assertEqual(spec.last,'000000114997')
        with self.assertRaises(ValueError): SequenceSpec('999999999999',2,1)
        with self.assertRaises(ValueError): SequenceSpec('1',1,0)

    def test_save_sequence_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'codes.txt';spec=SequenceSpec('000000100000',3,3)
            spec.save(p)
            self.assertEqual(p.read_text().splitlines(),['000000100000','000000100003','000000100006'])
            before=p.read_bytes()
            with self.assertRaises(FileExistsError): spec.save(p)
            self.assertEqual(p.read_bytes(),before)

    def test_index_random_access_substring_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);p=folder/'codes.txt'
            p.write_text('000000100000\n000000100003\n000000100003\n000000100006\n',encoding='utf-8')
            index=SourceIndex.build(p,folder/'cache')
            self.assertEqual((index.count,index.unique),(4,3))
            self.assertEqual(index.row(3),'000000100003')
            self.assertEqual(index.rows(2,2),[(2,'000000100003'),(3,'000000100003')])
            self.assertEqual(index.find('10000'),[(1,'000000100000'),(2,'000000100003'),(3,'000000100003')])
            self.assertEqual(index.find('%'),[])
            with self.assertRaises(IndexError): index.row(5)
            self.assertTrue(index.unchanged())
            p.write_text('000000000001\n',encoding='utf-8')
            self.assertFalse(index.unchanged())

    def test_disk_budget_allocation_both_and_reserve(self):
        # Ten outputs at 1 KiB, one allocation block each, plus explicit temp/report.
        budget=estimate_space(10,'singles',1024,100*1024**3,temp_bytes=100,reports_bytes=200,allocation_unit=4096)
        expected=4*(10*4096+100+200)+10*1024**3
        self.assertEqual(budget.required_bytes,expected)
        both=estimate_space(10,'both',1024,100*1024**3,temp_bytes=100,reports_bytes=200,allocation_unit=4096)
        self.assertGreater(both.required_bytes,budget.required_bytes)
        self.assertFalse(estimate_space(1000,'singles',4096,1024).enough)

    def test_approval_binds_order_and_destination(self):
        approval=JobApproval();job={'source':'hash','count':2,'ink':[0,0,0,100]}
        approval.approve(job,'folder',100)
        self.assertTrue(approval.valid(job,'folder',101))
        self.assertFalse(approval.valid({**job,'count':3},'folder',101))
        self.assertFalse(approval.valid(job,'other',101))
        self.assertFalse(approval.valid(job,'folder',99))
        approval.invalidate();self.assertFalse(approval.valid(job,'folder',101))
