//
//  Acknowledgements.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import chaiMatchPattern from 'chai-match-pattern';
import { use, expect } from 'chai';
import sinon from 'sinon';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import Acknowledgements from '@pages/Applications/Acknowledgements/Acknowledgements.vue';
import { CompactSerializer, CompactType } from '@models/Compact/Compact.model';
import { ApplicationSection } from '@models/Application/Application.model';
import { dataApi as mockDataApi } from '@network/mocks/mock.data.api';
import store from '@store/index';
import { nextTick } from 'vue';
import { flushPromises } from '@vue/test-utils';

use(chaiMatchPattern);

const firstStatementKey = 'attestation-home-state-is-psypact-state-with-active-license';
const factualKey = 'attestation-information-presented-is-factual';

const mountPage = async (applicationId: string, mountFn = mountFull) => {
    const wrapper = await mountFn(Acknowledgements);
    const component = wrapper.vm;

    await flushPromises();
    await component.$router.push({
        name: 'ApplicationAcknowledgements',
        params: { compact: CompactType.PSYPACT, applicationId },
    });
    await component.fetchApplication();
    await nextTick();

    return wrapper;
};

describe('Acknowledgements page', async () => {
    beforeEach(async () => {
        await store.dispatch('user/setCurrentCompact', CompactSerializer.fromServer({ type: CompactType.PSYPACT }));
    });
    afterEach(() => {
        mockDataApi.resetCreatedApplications();
    });
    it('should mount the page component', async () => {
        const wrapper = await mountShallow(Acknowledgements);

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(Acknowledgements).exists()).to.equal(true);
    });
    it('should mock populate a valid form, scroll to the save button, and clear the form', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;
        const scrollStub = sinon.stub(component, 'scrollToElement');

        await component.handleMockPopulate();

        expect(component.isFormValid).to.equal(true);
        expect(scrollStub.calledOnceWith(component.formData.submit.id)).to.equal(true);

        expect(component.formData.signatureName.value).to.equal('Test Applicant');

        await component.handleClearForm();

        expect(component.formData.signatureName.value).to.equal('');
        expect(component.isFormValid).to.equal(false);
    });
    it('should display yes / no statements, the static sign and submit text, and the signature', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;
        const signAndSubmit = component.signAndSubmitAttestation;

        expect(component.sectionKey).to.equal(ApplicationSection.ACKNOWLEDGEMENTS);
        expect(wrapper.find('.section-title').text()).to.equal('Acknowledgements and signature');
        expect(wrapper.findAll('.statements-list .question-row').length).to.equal(7);
        expect(wrapper.find('.statements-list .question-row input[type="radio"]').exists()).to.equal(true);
        expect(component.formData[firstStatementKey].value).to.equal(null);
        expect(component.formData['attestation-sign-and-submit']).to.equal(undefined);
        expect(wrapper.find('.sign-and-submit-text').text()).to.equal(signAndSubmit.text.trim());
        expect(wrapper.find('.factual-checkbox').exists()).to.equal(true);
        expect(component.formData.signatureName.value).to.equal('');
    });
    it('should only accept yes answers for the statements', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;
        const { formData } = component;

        component.validateAll({ asTouched: true, skipErrorScroll: true });

        expect(formData[firstStatementKey].errorMessage).to.equal('Required');
        expect(formData[factualKey].errorMessage).to.equal('Required');
        expect(formData.signatureName.errorMessage).to.equal('Required field');

        formData[firstStatementKey].value = false;
        formData[firstStatementKey].validate();

        expect(formData[firstStatementKey].errorMessage).to.equal('Required');

        formData[firstStatementKey].value = true;
        formData[firstStatementKey].validate();

        expect(formData[firstStatementKey].isValid).to.equal(true);
    });
    it('should prep the section request data without changing the sign and submit attestation', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;
        const { formData } = component;

        component.statementAttestations.forEach((attestation) => {
            formData[component.getAttestationKey(attestation)].value = true;
        });
        formData[factualKey].value = true;
        formData.signatureName.value = ' Test Applicant ';

        const requestData: any = component.prepSectionRequestData();

        expect(requestData.signatureName).to.equal('Test Applicant');
        expect(requestData.attestations.length).to.equal(9);
        expect(requestData.attestations.every((attestation) =>
            Object.keys(attestation).sort().join(',') === 'attestationId,value,version')).to.equal(true);
        expect(requestData.attestations.find((attestation) =>
            attestation.attestationId === 'sign-and-submit').value).to.equal(null);
        expect(requestData.attestations.find((attestation) =>
            attestation.attestationId === 'information-presented-is-factual').value).to.equal(true);
        expect(requestData.attestations.find((attestation) =>
            attestation.attestationId === 'home-state-is-psypact-state-with-active-license').value).to.equal(true);
    });
    it('should save the section and continue to the checklist after the last section', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;
        const dispatchSpy = sinon.spy(store, 'dispatch');
        const pushStub = sinon.stub(component.$router, 'push');

        component.formData.signatureName.value = 'Updated Name';
        await component.handleSubmit();
        await nextTick();

        expect(dispatchSpy.calledWith('user/updateApplicationRequestLicensee')).to.equal(true);
        expect(component.isFormSuccessful).to.equal(true);
        expect(component.application.acknowledgements.signatureName).to.equal('Updated Name');
        expect(wrapper.find('.continue-button').exists()).to.equal(true);

        await wrapper.find('.continue-button input').trigger('click');
        dispatchSpy.restore();
        pushStub.restore();

        expect(pushStub.firstCall.args[0]).to.matchPattern({
            name: 'ApplicationChecklist',
            params: { compact: CompactType.PSYPACT, applicationId: '2' },
        });
    });
    it('should hide the continue button after further edits', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        await component.handleSubmit();
        await nextTick();

        expect(component.isFormSuccessful).to.equal(true);

        component.formData.signatureName.value = 'Another Name';
        await nextTick();

        expect(component.isFormSuccessful).to.equal(false);
        expect(wrapper.find('.continue-button').exists()).to.equal(false);
    });
});
