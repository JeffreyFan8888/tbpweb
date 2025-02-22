from django.conf import settings
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.db import models
from django.db import transaction
from django.utils import timezone


# Mixins
class IDCodeMixin(models.Model):
    """
    This mixin provides a field that is to be used to store a unique identifier
    for a person. This can be a student ID or the RFID code for a campus ID
    card.
    """
    id_code = models.CharField(max_length=20, blank=True)

    class Meta(object):
        abstract = True


class University(models.Model):
    short_name = models.CharField(max_length=8, unique=True)
    long_name = models.CharField(max_length=64)
    website = models.URLField()

    def __str__(self):
        return self.long_name

    class Meta(object):
        ordering = ('long_name',)
        verbose_name_plural = 'universities'


class Major(models.Model):
    short_name = models.CharField(max_length=8)
    long_name = models.CharField(max_length=64)
    university = models.ForeignKey(University, on_delete=models.CASCADE)
    is_eligible = models.BooleanField(default=False)
    website = models.URLField()

    def __str__(self):
        return self.long_name

    class Meta(object):
        ordering = ('long_name',)
        unique_together = ('university', 'short_name')


class TermManager(models.Manager):
    def get_current_term(self):
        """Return the term with current set to True, or None if no current term
        exists.
        """
        term = cache.get('current_term')
        if not term:
            try:
                term = self.get(current=True)
                cache.set('current_term', term)
            except Term.DoesNotExist:
                pass
        return term

    def get_terms(self, include_future=False, include_summer=False,
                  include_unknown=False, reverse=False):
        """Get term objects according to optional criteria."""
        terms = self.all()

        if not include_unknown:
            terms = terms.exclude(term=Term.UNKNOWN)

        if not include_summer:
            terms = terms.exclude(term=Term.SUMMER)

        # Semester systems do not have a winter quarter.
        if getattr(settings, 'TERM_TYPE', 'quarter') == 'semester':
            terms = terms.exclude(term=Term.WINTER)

        if not include_future:
            current_term = self.get_current_term()
            if current_term:
                terms = terms.filter(id__lte=current_term.id)

        if reverse:
            return terms.order_by('-id')

        return terms

    def get_by_url_name(self, name):
        """
        The url param is generated by the get_url_name function. It takes the
        form of "fa2012".
        """
        if not isinstance(name, basestring):
            return None

        try:
            return self.get(term=name[0:2], year=name[2:])
        except Term.DoesNotExist:
            return None
        except ValueError:
            return None

    def get_by_natural_key(self, term, year):
        try:
            return self.get(term=term, year=year)
        except Term.DoesNotExist:
            return None


class Term(models.Model):
    """
    Refers to a school's quarter or semester system.
    Almost all models refer to this for the current term in the school year.
    """
    # Constants
    UNKNOWN = 'un'
    WINTER = 'wi'
    SPRING = 'sp'
    SUMMER = 'su'
    FALL = 'fa'

    TERM_CHOICES = (
        (UNKNOWN, 'Unknown'),
        (WINTER, 'Winter'),
        (SPRING, 'Spring'),
        (SUMMER, 'Summer'),
        (FALL, 'Fall'),
    )

    TERM_MAPPING = {
        UNKNOWN: 0,
        WINTER: 1,
        SPRING: 2,
        SUMMER: 3,
        FALL: 4
    }

    # pylint: disable=C0103
    id = models.IntegerField(primary_key=True)
    term = models.CharField(max_length=2, choices=TERM_CHOICES)
    year = models.PositiveSmallIntegerField()
    current = models.BooleanField(default=False)

    objects = TermManager()

    def save(self, *args, **kwargs):
        """
        We need to only have one current term. We'll do this by setting all
        other term's current bit to false, and then update our own. We can
        allow a case where there is NO current term. Infinite recursion cannot
        happen since updates only happen for objects with current=True.
        TODO(wli): Is this threadsafe? Does transaction.atomic() work properly?
        """
        if self.term == Term.UNKNOWN and self.year == 0:
            return

        # Make sure the term and year always map to the correct id.
        if (self.id is not None and
            (self.year != self.id // 10 or
             self.__term_as_int() != self.id % 10)):
            raise ValueError('You cannot update the year or term without '
                             'also updating the primary key value.')

        # Set the ID for a new object.
        # pylint: disable=C0103
        # pylint: disable=W0201
        self.id = self._calculate_pk()

        # Failed transactions will be rolled back, but will not catch errors
        with transaction.atomic():
            if self.current:
                Term.objects.filter(current=True).exclude(
                    id=self.id).update(current=False)
            super(Term, self).save(*args, **kwargs)
            self.update_term_officer_groups()
            if self.current:
                cache.set('current_term', self)  # Update the cache

    def verbose_name(self):
        """Returns the verbose name of this object in this form: Fall 2012."""
        return '%s %d' % (self.get_term_display(), self.year)

    def get_url_name(self):
        """Returns the serialized version for use in URL params."""
        return self.term + str(self.year)

    def natural_key(self):
        return (self.term, self.year)

    def __str__(self):
        name = self.verbose_name()
        if self.current:
            name += ' (Current)'
        return name

    def _calculate_pk(self):
        return self.year * 10 + self.__term_as_int()

    def __term_as_int(self):
        """Converts the term to a numeric mapping for the primary key."""
        return Term.TERM_MAPPING[self.term]

    def __lt__(self, other):
        if not isinstance(other, Term):
            other = Term(year=timezone.now().year,
                         term=Term.UNKNOWN)
        if self.year < other.year:
            return True
        elif self.year > other.year:
            return False
        else:
            return self.__term_as_int() < other.__term_as_int()

    def __le__(self, other):
        if not isinstance(other, Term):
            other = Term(year=timezone.now().year,
                         term=Term.UNKNOWN)
        return not other.__lt__(self)

    def __eq__(self, other):
        if not isinstance(other, Term):
            other = Term(year=timezone.now().year,
                         term=Term.UNKNOWN)
        return self.term == other.term and self.year == other.year

    def __ne__(self, other):
        if not isinstance(other, Term):
            other = Term(year=timezone.now().year,
                         term=Term.UNKNOWN)
        return not self.__eq__(other)

    def __gt__(self, other):
        if not isinstance(other, Term):
            other = Term(year=timezone.now().year,
                         term=Term.UNKNOWN)
        return other.__lt__(self)

    def __ge__(self, other):
        if not isinstance(other, Term):
            other = Term(year=timezone.now().year,
                         term=Term.UNKNOWN)
        return not self.__lt__(other)

    def update_term_officer_groups(self):
        """Ensure that if the term being saved is set as the "current" term,
        all groups that are specific to the current term are updated.
        """
        if self.current:
            # Clear out all existing "current term" groups, since the new
            # current term is being saved here.
            groups = Group.objects.filter(name__contains='Current')
            for group in groups:
                group.user_set.clear()

            # Update groups for all officers from this new current term
            officers = Officer.objects.filter(term=self)
            for officer in officers:
                officer._add_user_to_officer_groups()

    class Meta(object):
        ordering = ('id',)
        unique_together = ('term', 'year')


class OfficerPosition(models.Model):
    """An officer position for a student organization.

    Officer objects reference OfficerPositions to link users to the officer
    positions they have held.
    """
    short_name = models.CharField(max_length=16, unique=True)
    long_name = models.CharField(max_length=64, unique=True)
    executive = models.BooleanField(
        default=False,
        help_text='Is this an executive position (like President)?')
    auxiliary = models.BooleanField(
        default=False,
        help_text='Is this position auxiliary (i.e., not a core officer '
                  'position)?')
    mailing_list = models.CharField(
        max_length=16, blank=True,
        help_text='The mailing list name, not including the @domain.')

    # Rank is used to provide an ordering on officers, where a low number
    # represents a higher rank (e.g., president might be given a rank of 1,
    # and vice president a rank of 2).
    rank = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta(object):
        ordering = ('rank',)

    def __str__(self):
        return self.long_name

    def natural_key(self):
        return (self.short_name,)

    def get_corresponding_groups(self, term=None):
        """Return a list of Django Auth Group objects corresponding to this
        officer position and the term provided.

        For every officer position, there will be two directly associated
        Groups. One Group will have the same name as the officer position
        (long_name). The other Group will have that name, prefixed with
        "Current ". The "Current <long_name>" position refers to users who hold
        the officer position in the current term.

        Each officer position will also correspond to the "Executive" groups
        if the position has the executive field set to True. Each position will
        also correspond to the "Officer" groups if the auxiliary field is set
        to False.

        This method includes the "Current" groups in the result only if the
        term given is the current term.
        """
        is_current_term = term.current if term else False

        # Initialize the list of group names with the current officer position
        # name:
        group_names = [self.long_name]

        # This position is part of the Officer group, unless it is an auxiliary
        # position:
        if not self.auxiliary:
            group_names.append('Officer')

        if self.executive:
            group_names.append('Executive')

        groups = []  # List of Group objects to return
        for group_name in group_names:
            group, _ = Group.objects.get_or_create(name=group_name)
            groups.append(group)
            if is_current_term:
                current_group_name = 'Current {}'.format(group_name)
                group, _ = Group.objects.get_or_create(name=current_group_name)
                groups.append(group)

        return groups


class Officer(models.Model):
    """An officer of a student organization."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    position = models.ForeignKey(OfficerPosition, on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)

    is_chair = models.BooleanField(
        default=False,
        help_text='Is this person the chair of their committee?')

    class Meta(object):
        unique_together = ('user', 'position', 'term')
        permissions = (
            ('view_officer_contacts', 'Can view officer contact information'),
        )

    def __str__(self):
        return '%s - %s (%s %d)' % (
            self.user.get_username(), self.position.short_name,
            self.term.get_term_display(), self.term.year)

    def position_name(self):
        name = self.position.long_name
        if self.is_chair:
            name += ' Chair'
        return name

    def _add_user_to_officer_groups(self):
        """Add this Officer user to the corresponding officer position auth
        groups.
        """
        groups = self.position.get_corresponding_groups(term=self.term)
        self.user.groups.add(*groups)

    def _remove_user_from_officer_groups(self):
        """Remove this Officer user from the corresponding officer position auth
        groups that the user would not be a part of without this Officer object.

        This method, unlike _add_user_to_officer_groups, cannot simply remove
        all groups corresponding to this officer position. The method must only
        remove groups which the user would not be a part of without this
        specific Officer object. Otherwise, this method would remove groups
        that the user should remain a part of.
        """
        stale_groups = set(
            self.position.get_corresponding_groups(term=self.term))

        # Get a set of the officer groups the user should still be a part of:
        groups = set()
        officers = Officer.objects.filter(user=self.user).select_related(
            'position')
        for officer in officers:
            groups.update(officer.position.get_corresponding_groups(
                term=officer.term))

        # Get the set of officer groups that should be removed but subtracting
        # out the ones that are still needed:
        stale_groups = stale_groups.difference(groups)

        # Remove the user from these "stale" groups:
        self.user.groups.remove(*stale_groups)


def officer_post_save(sender, instance, *args, **kwargs):
    """Ensure that the user for a new Officer object is added to the
    corresponding auth groups.
    """
    instance._add_user_to_officer_groups()


def officer_post_delete(sender, instance, *args, **kwargs):
    """Ensure that the user for a new Officer object is removed from the
    corresponding auth groups.
    """
    instance._remove_user_from_officer_groups()


models.signals.post_save.connect(officer_post_save, sender=Officer)
models.signals.post_delete.connect(officer_post_delete, sender=Officer)
