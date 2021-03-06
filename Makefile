TEST_TARGETS=zhenech_DASH_katello-client\:el5 zhenech_DASH_katello-client\:el6 zhenech_DASH_katello-client\:el7
USE_SELINUX=$(shell test -d /sys/fs/selinux && echo ":Z")

test: $(addprefix test-,$(TEST_TARGETS))
	flake8 --ignore E501 ./bin/* src/ || true

test-%:
	docker run -it --volume $(CURDIR):/app$(USE_SELINUX) --workdir=/app $(subst _DASH_,/,$*) python -m compileall src/
	docker run -it --volume $(CURDIR):/app$(USE_SELINUX) --env PYTHONPATH=src/yum-plugins/ \
		--workdir=/app $(subst _DASH_,/,$*) \
		bash -c \
			'for binary in bin/*; do \
				if [ "$${binary}" = "bin/katello-tracer-upload" ]; then \
					continue; \
				fi; \
				python -- $${binary} --help; \
			done'
