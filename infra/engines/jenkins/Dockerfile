FROM jenkins/jenkins:2.541.2-jdk21

# Skip the setup wizard (handled via JCasC and init scripts)
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false -Dhudson.security.csrf.GlobalCrumbIssuerConfiguration.DISABLE_CSRF_PROTECTION=true"

# Tell Jenkins where to find the JCasC config
ENV CASC_JENKINS_CONFIG=/usr/share/jenkins/ref/casc.yaml

# Install plugins from plugins.txt
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
