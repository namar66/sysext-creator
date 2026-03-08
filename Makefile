NAME := sysext-creator
SPEC := $(NAME).spec
VERSION := $(shell awk '/^Version:/ { print $$2 }' $(SPEC))
TARFILE := $(NAME)-$(VERSION).tar.gz

.PHONY: srpm clean

$(TARFILE):
	git archive --prefix=$(NAME)-$(VERSION)/ --format=tar.gz HEAD > $(TARFILE)

srpm: $(TARFILE)
	rpmbuild -bs \
		--define "_sourcedir $(PWD)" \
		--define "_srcrpmdir $(outdir)" \
		$(SPEC)

clean:
	rm -f *.tar.gz *.src.rpm
