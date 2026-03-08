NAME := sysext-creator
SPEC := $(NAME).spec
VERSION := $(shell awk '/^Version:/ { print $$2 }' $(SPEC))
TARFILE := $(NAME)-$(VERSION).tar.gz

.PHONY: srpm clean

$(TARFILE):
	tar --exclude-vcs --exclude=$(TARFILE) --transform 's,^\./,$(NAME)-$(VERSION)/,' -czf $(TARFILE) .

srpm: $(TARFILE)
	rpmbuild -bs \
		--define "_sourcedir $(CURDIR)" \
		--define "_srcrpmdir $(outdir)" \
		$(SPEC)

clean:
	rm -f *.tar.gz *.src.rpm
