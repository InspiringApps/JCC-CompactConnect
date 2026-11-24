//
//  PersonalInformation.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import chaiMatchPattern from 'chai-match-pattern';
import { use, expect } from 'chai';
import sinon from 'sinon';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import PersonalInformation from '@pages/Applications/PersonalInformation/PersonalInformation.vue';
import { CompactSerializer, CompactType } from '@models/Compact/Compact.model';
import { ApplicationSection } from '@models/Application/Application.model';
import { dataApi as mockDataApi } from '@network/mocks/mock.data.api';
import store from '@store/index';
import { nextTick } from 'vue';
import { flushPromises } from '@vue/test-utils';

use(chaiMatchPattern);

const mountPage = async (applicationId: string, mountFn = mountFull) => {
    const wrapper = await mountFn(PersonalInformation);
    const component = wrapper.vm;

    await flushPromises();
    await component.$router.push({
        name: 'ApplicationPersonalInformation',
        params: { compact: CompactType.PSYPACT, applicationId },
    });
    await component.fetchApplication();
    await nextTick();

    return wrapper;
};

describe('PersonalInformation page', async () => {
    beforeEach(async () => {
        await store.dispatch('user/setCurrentCompact', CompactSerializer.fromServer({ type: CompactType.PSYPACT }));
    });
    afterEach(() => {
        mockDataApi.resetCreatedApplications();
    });
    it('should mount the page component', async () => {
        const wrapper = await mountShallow(PersonalInformation);

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(PersonalInformation).exists()).to.equal(true);
    });
    it('should mock populate a valid form, scroll to the save button, and clear the form', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;
        const scrollStub = sinon.stub(component, 'scrollToElement');

        await component.handleMockPopulate();

        expect(component.isFormValid).to.equal(true);
        expect(scrollStub.calledOnceWith(component.formData.submit.id)).to.equal(true);

        expect(component.formData.firstName.value).to.equal('Test');
        expect(component.selectedLanguages.length).to.equal(2);
        expect(component.formData.phone.value).to.equal('+13035551234');
        expect((wrapper.find('#phone').element as HTMLInputElement).value).to.equal('(303) 555-1234');

        await component.handleClearForm();

        expect(component.formData.firstName.value).to.equal('');
        expect(component.formData.ssnLastFour.value).to.equal('');
        expect(component.formData.languages.value).to.matchPattern([]);
        expect(component.isFormValid).to.equal(false);
    });
    it('should display a blank form for a started application', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;

        expect(component.sectionKey).to.equal(ApplicationSection.PERSONAL_INFORMATION);
        expect(wrapper.find('.section-title').text()).to.equal('Personal information');
        expect(wrapper.find('.back-link').text()).to.equal('Back to checklist');
        expect(wrapper.find('.attention-banner').exists()).to.equal(false);
        expect(component.formData.firstName.value).to.equal('');
        expect(component.formData.languages.value).to.matchPattern([]);
        expect(wrapper.find('.continue-button').exists()).to.equal(false);
    });
    it('should populate the form from an existing application', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;

        expect(component.formData.firstName.value).to.equal('Test');
        expect(component.formData.mailingState.value).to.equal('co');
        expect(component.formData.citizenship.value).to.equal('us');
        expect(wrapper.findAll('.language-pill').map((pill) => pill.text())).to.matchPattern(['English', 'Spanish']);
        expect(component.formData.languageSelect.valueOptions.some((option) => option.value === 'en')).to.equal(false);
    });
    it('should include emoji flags in the citizenship options', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;
        const unitedStates = component.citizenshipOptions.find((option) => option.value === 'us');

        expect(component.citizenshipOptions[0].value).to.equal('');
        expect(unitedStates.name).to.equal('🇺🇸 United States');
    });
    it('should add and remove languages as pills', async () => {
        const wrapper = await mountPage('1');
        const component = wrapper.vm;

        component.formData.languageSelect.value = 'fr';
        component.addLanguage();
        component.formData.languageSelect.value = 'de';
        component.addLanguage();
        await nextTick();

        expect(component.formData.languages.value).to.matchPattern(['fr', 'de']);
        expect(component.formData.languageSelect.value).to.equal('');
        expect(wrapper.findAll('.language-pill').map((pill) => pill.text())).to.matchPattern(['French', 'German']);

        await wrapper.find('.remove-language').trigger('click');

        expect(component.formData.languages.value).to.matchPattern(['de']);
        expect(component.formData.languageSelect.valueOptions.some((option) => option.value === 'fr')).to.equal(true);
    });
    it('should validate required, max length, and format rules', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;
        const { formData } = component;

        formData.firstName.value = 'a'.repeat(81);
        formData.ssnLastFour.value = '12a4';
        formData.npi.value = '123';
        formData.mailingZip.value = '1234';
        formData.phone.value = '+13031111111';
        formData.altPhone.value = '';
        component.validateAll({ asTouched: true, skipErrorScroll: true });

        expect(formData.firstName.errorMessage).to.equal('Must be less than or equal to 80 characters');
        expect(formData.lastName.errorMessage).to.equal('Required field');
        expect(formData.middleName.isValid).to.equal(true);
        expect(formData.ssnLastFour.errorMessage).to.equal('Must be 4 digits');
        expect(formData.npi.errorMessage).to.equal('Must be 10 digits');
        expect(formData.mailingZip.errorMessage)
            .to.equal('Must be a 5 digit zip code or a 9 digit zip code (12345-6789)');
        expect(formData.phone.errorMessage)
            .to.equal('Must be a valid phone number, including area code, for the selected country');
        expect(formData.altPhone.isValid).to.equal(true);

        formData.mailingZip.value = '12345-6789';
        formData.mailingZip.validate();

        expect(formData.mailingZip.isValid).to.equal(true);
        expect(component.isFormValid).to.equal(false);
    });
    it('should prep the section request data', async () => {
        const wrapper = await mountPage('2', mountShallow);
        const component = wrapper.vm;

        component.formData.middleName.value = '';

        expect(component.prepSectionRequestData()).to.matchPattern({
            firstName: 'Test',
            middleName: null,
            lastName: 'Applicant',
            suffix: null,
            phone: '+13035550100',
            altPhone: null,
            dob: component.applicationData.personalInformation.dob,
            ssnLastFour: '1111',
            npi: '1111111111',
            gender: 'male',
            professionalName: 'Test Applicant, PhD.',
            citizenship: 'us',
            placeOfBirth: 'Springfield',
            languages: ['en', 'es'],
            mailingAddress1: '123 Fake St',
            mailingAddress2: 'Apt 1',
            mailingCity: 'Springfield',
            mailingState: 'co',
            mailingZip: '11111',
        });
    });
    it('should save the section and show the continue button', async () => {
        const wrapper = await mountPage('2');
        const component = wrapper.vm;
        const dispatchSpy = sinon.spy(store, 'dispatch');

        component.formData.firstName.value = 'Updated';
        await component.handleSubmit();
        await nextTick();
        dispatchSpy.restore();

        const updateCall = dispatchSpy.getCalls().find((call) => call.args[0] === 'user/updateApplicationRequestLicensee');

        expect(updateCall.args[1].data.id).to.equal('2');
        expect(updateCall.args[1].data.personalInformation.firstName).to.equal('Updated');
        expect(component.isFormSuccessful).to.equal(true);
        expect(component.application.personalInformation.firstName).to.equal('Updated');
        expect(wrapper.find('.continue-button').exists()).to.equal(true);
        expect(component.nextRoute).to.matchPattern({
            name: 'ApplicationLicenseHistory',
            params: { compact: CompactType.PSYPACT, applicationId: '2' },
        });
    });
    it('should not save when the form is invalid', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;
        const dispatchSpy = sinon.spy(store, 'dispatch');

        await component.handleSubmit();
        dispatchSpy.restore();

        expect(dispatchSpy.calledWith('user/updateApplicationRequestLicensee')).to.equal(false);
        expect(component.isFormSuccessful).to.equal(false);
    });
    it('should display a load error when the application cannot be found', async () => {
        const wrapper = await mountPage('not-a-real-application');

        expect(wrapper.vm.isLoadError).to.equal(true);
        expect(wrapper.find('.section-load-error').exists()).to.equal(true);
        expect(wrapper.find('.section-form').exists()).to.equal(false);
    });
    it('should display the needs attention banner with reviewer notes', async () => {
        const wrapper = await mountPage('1', mountShallow);
        const component = wrapper.vm;

        component.fetchedApplication.personalInformation.applicantStatus = 'needs-attention';
        component.fetchedApplication.personalInformation.reviews = [{ notesForApplicant: 'Fix your name.' }];

        expect(component.isNeedsAttention).to.equal(true);
        expect(component.attentionNotes).to.matchPattern(['Fix your name.']);
    });
});
