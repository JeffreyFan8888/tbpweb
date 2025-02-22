# pylint: disable=W0402
import string

from django.urls import reverse
from django.db import models
from django.template.defaultfilters import slugify

from base.models import Term


class Department(models.Model):
    long_name = models.CharField(
        max_length=100,
        help_text='Full name for department (e.g. Computer Science)')
    short_name = models.CharField(
        max_length=25,
        unique=True,
        help_text='Colloquial shorthand for department (e.g. CS)')
    abbreviation = models.CharField(
        max_length=25,
        help_text=('Standardized abbreviation for department from '
                   'the registrar (e.g. COMPSCI)'))
    slug = models.SlugField(
        max_length=25,
        editable=False)

    class Meta(object):
        ordering = ('long_name',)

    def __str__(self):
        return self.long_name

    def get_absolute_url(self):
        return reverse('courses:course-list', args=(self.slug,))

    def save(self, *args, **kwargs):
        self.slug = slugify(self.short_name)
        self.abbreviation = self.abbreviation.upper().strip()
        super(Department, self).save(*args, **kwargs)


class Course(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    number = models.CharField(max_length=10, db_index=True)
    title = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    class Meta(object):
        unique_together = ('department', 'number')

    def __lt__(self, other):
        if not isinstance(other, Course):
            return False
        # Compare departments of courses
        if self.department.abbreviation < other.department.abbreviation:
            return True
        elif self.department.abbreviation > other.department.abbreviation:
            return False
        our_number = self.number
        oth_number = other.number
        our_hyph = 0
        oth_hyph = 0

        if '-' in self.number:
            our_hyph = int(our_number.split('-', 1)[1])
            our_number = our_number.split('-', 1)[0]
        if '-' in other.number:
            oth_hyph = int(oth_number.split('-', 1)[1])
            oth_number = oth_number.split('-', 1)[0]

        our_int = int(our_number.strip(string.letters))
        oth_int = int(oth_number.strip(string.letters))

        our_post = our_number.lstrip(string.letters)
        oth_post = oth_number.lstrip(string.letters)

        # Compare integer part of course numbers
        if our_int < oth_int:
            return True
        elif our_int > oth_int:
            return False
        # Compare postfix letters of course numbers
        elif our_post < oth_post:
            return True
        elif our_post > oth_post:
            return False
        # Compare prefix letters of the course numbers
        elif our_number < oth_number:
            return True
        elif our_number > oth_number:
            return False
        # Compare hyphenated
        else:
            return our_hyph < oth_hyph

    def __le__(self, other):
        if not isinstance(other, Course):
            return False
        return not other.__lt__(self)

    def __eq__(self, other):
        if not isinstance(other, Course):
            return False
        return (self.number == other.number and
                self.department.id == other.department.id)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        if not isinstance(other, Course):
            return False
        return other.__lt__(self)

    def __ge__(self, other):
        if not isinstance(other, Course):
            return False
        return not self.__lt__(other)

    def __str__(self):
        return self.abbreviation()

    def abbreviation(self):
        """Return an abbreviated name for the course.

        For instance, "CS 61A".
        """
        return '{} {}'.format(self.department.short_name, self.number)

    def get_display_name(self):
        """Return the standard display name for the course.

        For instance, "Computer Science 61A".
        """
        return '{} {}'.format(self.department.long_name, self.number)

    def get_url_name(self):
        """Return the URL name for the course.

        For example, "cs61A".
        """
        return '{}{}'.format(self.department.slug, self.number)

    def get_absolute_url(self):
        return reverse('courses:course-detail', args=(
            self.department.slug, self.number))

    def save(self, *args, **kwargs):
        self.number = self.number.upper().strip()
        super(Course, self).save(*args, **kwargs)


class Instructor(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    middle_initial = models.CharField(max_length=1, blank=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    website = models.URLField(blank=True)

    class Meta(object):
        ordering = ('last_name', 'first_name', 'middle_initial')
        unique_together = (
            'first_name', 'middle_initial', 'last_name', 'department')

    def __str__(self):
        return self.full_name()

    def full_name(self):
        return '{} {}'.format(self.first_name, self.last_name)

    def last_name_first(self):
        """Return the instructor's name as "last_name, first_name" if
        first_name is not None, and "last_name" otherwise.
        """
        if self.first_name:
            return '{}, {}'.format(self.last_name, self.first_name)
        else:
            return self.last_name

    def get_absolute_url(self):
        return reverse('courses:instructor-detail', args=(self.pk,))


class CourseInstance(models.Model):
    # Allow terms to be null because some exams have unknown years
    term = models.ForeignKey(Term, null=True, on_delete=models.SET_NULL)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    instructors = models.ManyToManyField(Instructor)

    def __str__(self):
        return '{} - {}'.format(self.course, self.term)
