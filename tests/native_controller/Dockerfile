FROM node@sha256:63538dfe497cc29dfafdda25ada09b46db68a3f4cc205abf1f5d6bf0913f3384
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources && apt-get -o Acquire::Retries=3 update && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends qtbase5-dev qtbase5-dev-tools && rm -rf /var/lib/apt/lists/*
COPY fake-root.sh /bin/__root
RUN chmod 755 /bin/__root
