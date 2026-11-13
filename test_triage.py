import unittest

from triage import analyze_issue


def ticket(subject, description='', assigned=None, project_id=12):
    return {
        'subject': subject,
        'description': description,
        'assigned_to': {'id': assigned} if assigned else None,
        'project': {'id': project_id},
    }


class TriageTests(unittest.TestCase):
    def test_unassigned_hardware_failure_is_candidate(self):
        item = analyze_issue(ticket('Nefunguje tiskárna', 'Potřebujeme opravu'))
        self.assertEqual(item['action'], 'auto_candidate')
        self.assertEqual(item['confidence'], 'high')
        self.assertIn('tiskárna', item['devices'])

    def test_device_without_failure_requires_review(self):
        item = analyze_issue(ticket('Potřebujeme novou čtečku'))
        self.assertEqual(item['action'], 'review')

    def test_healthy_device_not_auto_assigned(self):
        item = analyze_issue(ticket('Tiskárna funguje, problém je v reportu'))
        self.assertNotEqual(item['action'], 'auto_candidate')

    def test_negative_and_positive_in_separate_clauses(self):
        item = analyze_issue(ticket('Tiskárna funguje, ale čtečka nefunguje'))
        self.assertEqual(item['action'], 'auto_candidate')
        self.assertEqual(item['faults'], ['nefunguje'])

    def test_software_failure_not_hardware(self):
        item = analyze_issue(ticket('Nefunguje aplikace při tisku'))
        self.assertEqual(item['action'], 'none')

    def test_driver_issue_requires_review(self):
        item = analyze_issue(ticket('Problém s ovladačem tiskárny'))
        self.assertEqual(item['action'], 'review')

    def test_existing_assignee_never_candidate(self):
        item = analyze_issue(ticket('Rozbitý terminál', assigned=55))
        self.assertEqual(item['action'], 'none')

    def test_other_project_never_candidate(self):
        item = analyze_issue(ticket('Rozbitý terminál', project_id=88))
        self.assertEqual(item['action'], 'none')

    def test_diacritics_and_ascii_equivalent(self):
        first = analyze_issue(ticket('VADNÁ ČTEČKA'))
        second = analyze_issue(ticket('Vadna ctecka'))
        self.assertEqual(first['action'], 'auto_candidate')
        self.assertEqual(first['devices'], second['devices'])

    def test_empty_ticket(self):
        self.assertEqual(analyze_issue(ticket(''))['action'], 'none')


if __name__ == '__main__':
    unittest.main()
