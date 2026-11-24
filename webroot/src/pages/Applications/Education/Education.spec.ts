//
//  Education.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import chaiMatchPattern from 'chai-match-pattern';
import { use, expect } from 'chai';
import sinon from 'sinon';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import Education from '@pages/Applications/Education/Education.vue';
import { CompactSerializer, CompactType } from '@models/Compact/Compact.model';
import { ApplicationSection } from '@models/Application/Application.model';
import { dataApi as mockDataApi } from '@network/mocks/mock.data.api';
import store from '@store/index';
import { nextTick } from 'vue';
import { flushPromises } from '@vue/test-utils';

use(chaiMatchPattern);

const contactAttestationKey = 'contact-education-institutional-verification';

const mountPage = async (applicationId: string, mountFn = mountFull) => {
    const wrapper = await mountFn(Education);
    const component = wrapper.vm;

    await flushPromises();
    await component.$router.push({
        name: 'ApplicationEducation',
        params: { compact: CompactType.PSYPACT, applicationId },
    });
    await component.fetchApplication();
    await nextTick();

    return wrapper;
};

describe('Education page', async () => {
    beforeEach(async () => {
        await store.dispatch('user/setCurrentCompact', CompactSerializer.fromServer({ type: CompactType.PSYPACT }));
    });
    afterEach(() => {
        mockDataApi.resetCreatedApplications();
    });
    it('should mount the page component', async () => {
        const wrapper = await mountShallow(Education);

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(Education).exists()).to.equal(true);
    });
    it('should mock populate a valid form, scroll to the save button, and clear the form', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;
        const scrollStub = sinon.stub(component, 'scrollToElement');

        await component.handleMockPopulate();

        expect(component.isFormValid).to.equal(true);
        expect(scrollStub.calledOnceWith(component.formData.submit.id)).to.equal(true);

        await component.handleClearForm();

        expect(component.formData.institution.value).to.equal('');
        expect(component.formData.isAccreditedByAuthority.value).to.equal(null);
        expect(component.verificationInputs.contactName.value).to.equal('');
        expect(component.isFormValid).to.equal(false);
    });
    it('should display a blank form with unanswered questions for a started application', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;

        expect(component.sectionKey).to.equal(ApplicationSection.EDUCATION);
        expect(wrapper.find('.section-title').text()).to.equal('Education');
        expect(component.formData.isCompleted.value).to.equal(null);
        expect(component.formData.isAccreditedByAuthority.value).to.equal(null);
        expect(component.degreeTypeOptions.map((option) => option.name))
            .to.matchPattern(['- Select -', 'PsyD', 'PhD', 'EdD']);
        expect(wrapper.findAll('.question-row').length).to.equal(4);
        expect(wrapper.find('.verification-panel').exists()).to.equal(false);
        expect(component.formData.contactName).to.equal(undefined);
    });
    it('should show and require institutional verification when the program was not accredited', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        component.formData.isAccreditedByAuthority.value = false;
        await nextTick();
        await nextTick();

        expect(component.isVerificationRequired).to.equal(true);
        expect(wrapper.find('.verification-panel').exists()).to.equal(true);
        expect(component.formData.contactName).to.not.equal(undefined);
        expect(component.formData[contactAttestationKey].value).to.equal(false);

        component.validateAll({ asTouched: true, skipErrorScroll: true });

        expect(component.isFormValid).to.equal(false);
        expect(component.formData.contactName.errorMessage).to.equal('Required field');
        expect(component.formData[contactAttestationKey].errorMessage).to.equal('Required');

        component.formData.isAccreditedByAuthority.value = true;
        await nextTick();
        await nextTick();

        expect(wrapper.find('.verification-panel').exists()).to.equal(false);
        expect(component.formData.contactName).to.equal(undefined);
    });
    it('should validate the accreditation year and allow the optional equivalency question', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;
        const { formData } = component;

        formData.accreditingYear.value = '20a1';
        component.validateAll({ asTouched: true, skipErrorScroll: true });

        expect(formData.accreditingYear.errorMessage).to.equal('Must be a 4 digit year');
        expect(formData.isCompleted.errorMessage).to.equal('Required field');
        expect(formData.isProgramEquivalent.isValid).to.equal(true);
    });
    it('should display the needs attention banner with reviewer notes', async () => {
        const wrapper = await mountPage('4');

        expect(wrapper.find('.attention-banner').exists()).to.equal(true);
        expect(wrapper.find('.attention-title').text()).to.equal('Issue with your application');
        expect(wrapper.find('.attention-note').text())
            .to.equal('Could not confirm your accredidation. Please provide an accrediting contact.');
    });
    it('should prep a reset accrediting contact when the program was accredited', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;
        const requestData = await component.prepSectionRequestData();

        expect(requestData).to.matchPattern({
            nameAtTime: 'Test Applicant',
            institution: 'University of Psychology',
            city: 'Springfield',
            state: 'co',
            degreeType: 'phd',
            program: 'Family, friends, & family friends',
            department: 'Psychology',
            conferredDate: component.sectionData.conferredDate,
            isCompleted: true,
            accreditingBody: 'University of Psychology',
            accreditingYear: component.sectionData.accreditingYear,
            isAccreditedByAuthority: true,
            isProgramEquivalent: true,
            hasResidence: true,
            accreditingContact: {
                name: null,
                email: null,
                city: null,
                state: null,
                zip: null,
                phone: null,
                attestations: [{
                    attestationId: 'education-institutional-verification',
                    version: '1',
                    value: null,
                }],
            },
            transcripts: [],
        });
    });
    it('should prep the accrediting contact when institutional verification is required', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;

        component.formData.isAccreditedByAuthority.value = false;
        await nextTick();
        await nextTick();

        const { formData } = component;

        formData.contactName.value = 'Dr. Contact';
        formData.contactEmail.value = 'contact@example.com';
        formData.contactCity.value = 'Boulder';
        formData.contactState.value = 'co';
        formData.contactZip.value = '80301';
        formData.contactPhone.value = '+13035551234';
        formData[contactAttestationKey].value = true;

        const requestData: any = await component.prepSectionRequestData();

        expect(requestData.isAccreditedByAuthority).to.equal(false);
        expect(requestData.accreditingContact).to.matchPattern({
            name: 'Dr. Contact',
            email: 'contact@example.com',
            city: 'Boulder',
            state: 'co',
            zip: '80301',
            phone: '+13035551234',
            attestations: [{
                attestationId: 'education-institutional-verification',
                version: '1',
                value: true,
            }],
        });
    });
    it('should save the section and route to conduct history next', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;
        const dispatchSpy = sinon.spy(store, 'dispatch');

        component.formData.department.value = 'Clinical Psychology';
        await component.handleSubmit();
        dispatchSpy.restore();

        expect(dispatchSpy.calledWith('user/updateApplicationRequestLicensee')).to.equal(true);
        expect(component.isFormSuccessful).to.equal(true);
        expect(component.application.education.department).to.equal('Clinical Psychology');
        expect(component.nextRoute).to.matchPattern({
            name: 'ApplicationConductHistory',
            params: { compact: CompactType.PSYPACT, applicationId: '2' },
        });
    });
});
